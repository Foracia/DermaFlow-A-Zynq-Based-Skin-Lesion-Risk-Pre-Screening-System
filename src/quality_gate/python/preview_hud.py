"""Small monochrome PS preview panel outside the hardware quality ROI.

Panel readings describe the latest completed statistics, not the displayed frame.
The panel is drawn after FPGA statistics and never supplies quality decisions.
"""
import base64
import json
import math
from pathlib import Path

import numpy as np

FONT_TEXT = (
    '质量门控开发预览目标原图剩余秒状态等待统计拒绝通过稳定中原因'
    '亮度偏低偏高暗像素过多亮像素过多清晰度分数低于阈值合格连续'
    '数据最近完成的统计未与显示帧精确绑定框内只放皮肤图像固定位置光照'
    '先勿切换素材限时结束后自动停止红框是规则待标定'
    '无有效结果过期请检查输入曝光合格清晰度合格'
    '准备阶段观察即将停止总剩余让屏幕朝镜头皮肤图片覆盖中央框自然手持允许轻微晃动无需完全静止调焦或切换素材结束后自动停止无需断电'
    '：；，。 /|[]#%.-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
)


def handheld_phase(elapsed):
    """Predetermined 45 s flow: 15 s setup, 25 s observation, 5 s finish."""
    if elapsed < 15:
        return 'setup', '准备阶段：剩余 %d 秒；让屏幕朝镜头，皮肤图片覆盖中央框' % max(0,math.ceil(15-elapsed))
    if elapsed < 40:
        return 'observation', '观察阶段：剩余 %d 秒；自然手持，先勿调焦或切换素材' % max(0,math.ceil(40-elapsed))
    return 'finishing', '即将停止：剩余 %d 秒；结束后自动停止，无需断电' % max(0,math.ceil(45-elapsed))


def describe(sample, cfg):
    """Explain exact integer criteria; display rounding never changes verdicts."""
    if not sample or not sample.get('present') or not sample.get('valid'):
        return '等待统计', '无有效结果'
    n, g = sample['pixel_count'], sample['gradient_count']
    if not n or not g:
        return '等待统计', '无有效结果'
    reasons = []
    if sample['luma_sum'] < cfg['mean_min'] * n:
        reasons.append('亮度偏低')
    if sample['luma_sum'] > cfg['mean_max'] * n:
        reasons.append('亮度偏高')
    if sample['dark_count'] * 10000 > cfg['dark_max_bp'] * n:
        reasons.append('暗像素过多')
    if sample['bright_count'] * 10000 > cfg['bright_max_bp'] * n:
        reasons.append('亮像素过多')
    if sample['gradient_sum'] < cfg['sharp_min'] * g:
        reasons.append('清晰度分数低于阈值')
    if reasons:
        return '拒绝', ' / '.join(reasons)
    return ('通过' if sample.get('stable_ok') else '稳定中'), '曝光合格 / 清晰度合格'


class PreviewHUD:
    TOP = (12, 12, 1256, 140)
    BOTTOM = (12, 590, 1256, 116)

    def __init__(self, font_path, *, target_label='A 原图'):
        if target_label not in ('A 原图', '皮肤'):
            raise ValueError('Unsupported preview target label')
        self.target_label = target_label
        data = json.loads(Path(font_path).read_text(encoding='utf-8'))
        self.height = data['height']
        self.glyphs = {}
        for char, item in data['glyphs'].items():
            bits = np.unpackbits(np.frombuffer(base64.b64decode(item['bits']), dtype=np.uint8))
            mask = bits[:self.height * item['width']].reshape(self.height, item['width'])
            self.glyphs[char] = mask.astype(bool)
        self.top = np.zeros((self.TOP[3], self.TOP[2], 4), dtype=np.uint8)
        self.bottom = np.zeros((self.BOTTOM[3], self.BOTTOM[2], 4), dtype=np.uint8)
        self.top[:, :, 3] = self.bottom[:, :, 3] = 255
        self.last_signature = None
        self.last_lines = []
        self.update_count = 0

    def validate_roi(self, cfg):
        for x, y, width, height in (self.TOP, self.BOTTOM):
            if not (x + width <= cfg['x0'] or cfg['x0'] + cfg['width'] <= x
                    or y + height <= cfg['y0'] or cfg['y0'] + cfg['height'] <= y):
                raise ValueError('Preview panel overlaps quality ROI')

    def _text(self, panel, line_number, text):
        y, x = 6 + line_number * 32, 12
        for char in text:
            glyph = self.glyphs.get(char)
            if glyph is None:
                raise ValueError('Preview font missing character: ' + char)
            width = glyph.shape[1]
            if x + width > panel.shape[1] - 8:
                raise ValueError('Preview line exceeds panel width')
            region = panel[y:y+self.height, x:x+width, :3]
            region[glyph] = 255
            x += width

    def draw(self, frame, sample, cfg, remaining, result_age=None, phase=None):
        if frame.shape != (720, 1280, 4) or frame.dtype != np.uint8:
            raise ValueError('HUD requires proven 720p four-byte pixel format')
        self.validate_roi(cfg)
        seconds = max(0, math.ceil(remaining))
        stale = sample is not None and result_age is not None and result_age > 1.0
        state, reason = describe(None if stale else sample, cfg)
        if stale:
            reason = '统计过期 / 请检查输入'
        signature = (sample.get('frame_id') if sample else None, seconds, stale, phase)
        if signature != self.last_signature:
            self.top[:, :, :3] = self.bottom[:, :, :3] = 0
            lines = [
                '质量门控开发预览 | 目标 %s | 剩余 %d 秒' % (self.target_label, seconds),
                '状态：%s | 原因：%s' % (state, reason),
            ]
            if sample and sample.get('valid') and sample['pixel_count'] and sample['gradient_count']:
                n, g = sample['pixel_count'], sample['gradient_count']
                lines.extend([
                    '亮度 %.1f [%d-%d] | 暗像素 %.2f%% / %.2f%% | 亮像素 %.2f%% / %.2f%%' % (
                        sample['luma_sum']/n, cfg['mean_min'], cfg['mean_max'],
                        sample['dark_count']*100/n, cfg['dark_max_bp']/100,
                        sample['bright_count']*100/n, cfg['bright_max_bp']/100),
                    '清晰度 %.2f / %d | 连续合格 %d / %d | 统计帧 #%d' % (
                        sample['gradient_sum']/g, cfg['sharp_min'], sample.get('stable_count',0),
                        cfg['stable_n'], sample['frame_id']),
                ])
            else:
                lines.extend(['等待统计', '数据：无有效结果'])
            for i, line in enumerate(lines):
                self._text(self.top, i, line)
            bottom = [
                '数据：最近完成的统计；未与显示帧精确绑定',
                phase or ('框内只放皮肤；固定位置光照' if self.target_label == '皮肤'
                          else '框内只放皮肤图像；固定位置光照，先勿切换素材'),
                '允许轻微晃动；无需完全静止 | 阈值待标定' if phase else '限时预览结束后自动停止；红框是规则拒绝，阈值待标定',
            ]
            for i, line in enumerate(bottom):
                self._text(self.bottom, i, line)
            self.last_signature = signature
            self.last_lines = lines + bottom
            self.update_count += 1
        for (x,y,width,height), panel in [(self.TOP,self.top),(self.BOTTOM,self.bottom)]:
            frame[y:y+height,x:x+width,:] = panel
        return state, reason
