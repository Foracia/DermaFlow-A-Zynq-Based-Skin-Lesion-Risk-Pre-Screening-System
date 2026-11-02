# -*- coding: utf-8 -*-
"""评估页 / 保存页的 HUD 面板。

与 `preview_hud.py` 的区别：
- `preview_hud` 是开发观察用，文字含"阈值待标定""未与显示帧精确绑定"等说明
- 本模块是**面向终端用户**的正式界面，只显示状态、关键指标和操作提示

面板位置固定在 ROI 之外（ROI y=180..539，上下面板分别在 0..100 和 640..720），
因此不会污染硬件质量统计区域。构造时会校验，相交则拒绝。
"""

from __future__ import annotations

import numpy as np

from ui_menu import FontSet, draw_text

# 面板几何（1280×720）
TOP_BOX = (0, 0, 1280, 104)
BOTTOM_BOX = (0, 636, 1280, 84)

C_PANEL_BG = (18, 20, 24)
C_LINE = (44, 48, 56)
C_MAIN = (235, 238, 242)
C_DIM = (150, 155, 165)
C_OK = (110, 230, 150)
C_WARN = (245, 205, 90)
C_BAD = (245, 120, 110)

LINE_PAD_X = 24
LINE1_DY = 8
LINE2_DY = 50


def _fill(arr, box, color):
    x, y, w, h = box
    arr[y:y + h, x:x + w, :3] = color


def _hairline(arr, y, color):
    arr[y:y + 2, :, :3] = color


def _overlaps(box, roi):
    x, y, w, h = box
    rx, ry, rw, rh = roi['x0'], roi['y0'], roi['width'], roi['height']
    return not (x + w <= rx or rx + rw <= x or y + h <= ry or ry + rh <= y)


class LiveHUD:
    """评估页与保存页的面板绘制。

    面板内容变化时才重绘（用 signature 判断），每帧只做两次整块拷贝。
    """

    def __init__(self, font24_path, *, roi):
        self.font = FontSet(font24_path)
        self.roi = dict(roi)
        for box in (TOP_BOX, BOTTOM_BOX):
            if _overlaps(box, roi):
                raise ValueError('HUD 面板与质量 ROI 重叠，拒绝绘制')

        self._top = np.zeros((TOP_BOX[3], TOP_BOX[2], 4), dtype=np.uint8)
        self._bottom = np.zeros((BOTTOM_BOX[3], BOTTOM_BOX[2], 4), dtype=np.uint8)
        self._top[:, :, 3] = 255
        self._bottom[:, :, 3] = 255
        self._sig = None
        self._off = (self.font.height - self.font.pixel_size) // 2

    # -- 文字 ------------------------------------------------------------
    def _put(self, panel, dy, text, color, x=None):
        y = dy - self._off
        if x is None:
            x = LINE_PAD_X
        draw_text(panel, self.font, x, y, text, color)

    def _put_right(self, panel, dy, text, color):
        w = self.font.text_width(text)
        self._put(panel, dy, text, color, x=panel.shape[1] - LINE_PAD_X - w)

    # -- 主接口 ----------------------------------------------------------
    def draw(self, frame, *, title, state_text, state_level, line2,
             hint, signature=None):
        """把面板画进 frame（就地修改）。

        title       左侧标题，如 '模式一 · 仅评估'
        state_text  右侧状态词，如 '通过' / '拒绝' / '等待统计'
        state_level 'ok' | 'warn' | 'bad'
        line2       第二行指标文字
        hint        底部提示
        """
        sig = (title, state_text, state_level, line2, hint) if signature is None else signature
        if sig != self._sig:
            self._top[:, :, :3] = C_PANEL_BG
            self._bottom[:, :, :3] = C_PANEL_BG
            _hairline(self._top, TOP_BOX[3] - 2, C_LINE)
            _hairline(self._bottom, 0, C_LINE)

            self._put(self._top, LINE1_DY, title, C_MAIN)
            color = {'ok': C_OK, 'warn': C_WARN, 'bad': C_BAD}.get(state_level, C_DIM)
            self._put_right(self._top, LINE1_DY, state_text, color)
            self._put(self._top, LINE2_DY, line2, C_DIM)

            self._put(self._bottom, 26, hint, C_DIM)
            self._sig = sig

        x, y, w, h = TOP_BOX
        frame[y:y + h, x:x + w, :] = self._top
        x, y, w, h = BOTTOM_BOX
        frame[y:y + h, x:x + w, :] = self._bottom
        return frame

    def invalidate(self):
        self._sig = None


# ---------------------------------------------------------------------------
# 状态文字：把质量门 sample 翻译成面向用户的短句
# ---------------------------------------------------------------------------
def describe_state(sample, cfg):
    """返回 (状态词, 颜色级别, 指标行)。"""
    if not sample or not sample.get('present') or not sample.get('valid'):
        return '等待统计', 'warn', '亮度 --   清晰度 --   连续 --'

    n = sample.get('pixel_count') or 0
    g = sample.get('gradient_count') or 0
    if not n or not g:
        return '等待统计', 'warn', '亮度 --   清晰度 --   连续 --'

    luma = sample['luma_sum'] / n
    sharp = sample['gradient_sum'] / g
    dark = sample['dark_count'] * 100.0 / n
    bright = sample['bright_count'] * 100.0 / n
    stable = sample.get('stable_count', 0)
    need = cfg.get('stable_n', 3)

    metrics = '亮度 %.1f   清晰度 %.1f   连续 %d/%d' % (luma, sharp, stable, need)

    if not sample.get('quality_ok'):
        reasons = []
        if sample['luma_sum'] < cfg['mean_min'] * n:
            reasons.append('偏暗')
        if sample['luma_sum'] > cfg['mean_max'] * n:
            reasons.append('偏亮')
        if sample['dark_count'] * 10000 > cfg['dark_max_bp'] * n:
            reasons.append('暗区过多')
        if sample['bright_count'] * 10000 > cfg['bright_max_bp'] * n:
            reasons.append('亮区过多')
        if sample['gradient_sum'] < cfg['sharp_min'] * g:
            reasons.append('不够清晰')
        return '拒绝：' + ' '.join(reasons), 'bad', metrics

    if sample.get('stable_ok'):
        return '通过', 'ok', metrics
    return '稳定中', 'warn', metrics


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
def _selftest():
    from pathlib import Path
    here = Path(__file__).resolve().parent

    print('=' * 66)
    print('评估页 HUD 自检')
    print('=' * 66)

    ok = 0
    fail = 0

    def check(name, cond):
        nonlocal ok, fail
        if cond:
            ok += 1
            print('  PASS  ' + name)
        else:
            fail += 1
            print('  FAIL  ' + name)

    roi = dict(x0=320, y0=180, width=640, height=360)
    hud = LiveHUD(here / 'ui_font_24.json', roi=roi)

    frame = np.full((720, 1280, 4), 90, dtype=np.uint8)
    frame[:, :, 3] = 255
    roi_before = frame[180:540, 320:960, :3].copy()

    hud.draw(frame, title='模式一 · 仅评估', state_text='通过', state_level='ok',
             line2='亮度 130.9   清晰度 22.0   连续 3/3', hint='KEY3 返回菜单')
    check('ROI 区域未被改写', np.array_equal(roi_before, frame[180:540, 320:960, :3]))
    check('顶部面板已绘制', not np.array_equal(frame[0:100, :, :3],
                                              np.full((100, 1280, 3), 90, dtype=np.uint8)))
    check('底部面板已绘制', not np.array_equal(frame[640:700, :, :3],
                                              np.full((60, 1280, 3), 90, dtype=np.uint8)))

    cfg = dict(mean_min=40, mean_max=210, dark_max_bp=500, bright_max_bp=200,
               sharp_min=20, stable_n=3)

    s_pass = dict(present=True, valid=True, quality_ok=True, stable_ok=True,
                  stable_count=3, pixel_count=640 * 360, gradient_count=638 * 358,
                  luma_sum=int(130 * 640 * 360), dark_count=0, bright_count=0,
                  gradient_sum=int(22 * 638 * 358))
    st, lvl, m = describe_state(s_pass, cfg)
    check('合格 -> 通过/ok', st == '通过' and lvl == 'ok')

    s_dark = dict(s_pass, quality_ok=False, stable_ok=False, stable_count=0,
                  luma_sum=int(32 * 640 * 360))
    st, lvl, m = describe_state(s_dark, cfg)
    check('偏暗 -> 拒绝/bad', st.startswith('拒绝') and lvl == 'bad' and '偏暗' in st)

    s_blur = dict(s_pass, quality_ok=False, stable_ok=False,
                  gradient_sum=int(6 * 638 * 358))
    st, lvl, m = describe_state(s_blur, cfg)
    check('不清晰 -> 拒绝/bad', '不够清晰' in st and lvl == 'bad')

    s_invalid = dict(s_pass, valid=False)
    st, lvl, m = describe_state(s_invalid, cfg)
    check('无效 -> 等待统计/warn', st == '等待统计' and lvl == 'warn')

    # 面板与 ROI 重叠应拒绝
    try:
        LiveHUD(here / 'ui_font_24.json', roi=dict(x0=0, y0=0, width=1280, height=720))
        check('面板与 ROI 重叠应拒绝', False)
    except ValueError:
        check('面板与 ROI 重叠被拒绝', True)

    # 输出样图
    try:
        from PIL import Image
        out = here.parent / 'build' / 'ui_menu_preview'
        out.mkdir(parents=True, exist_ok=True)
        Image.fromarray(frame[:, :, :3]).save(out / 'live_hud.png')
        print('  样图:', out / 'live_hud.png')
    except ImportError:
        pass

    print()
    print('结果: %d 通过 / %d 失败' % (ok, fail))
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(_selftest())
