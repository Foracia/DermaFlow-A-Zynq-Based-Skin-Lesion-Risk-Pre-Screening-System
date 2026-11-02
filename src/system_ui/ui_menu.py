# -*- coding: utf-8 -*-
"""菜单页绘制 —— 纯 numpy，板端不需要 PIL 或任何字体文件。

## 为什么单独一套字库

菜单用字与 `preview_hud.py` 的 HUD 用字重叠不多。
本模块自带 `UI_FONT_TEXT`（所有可能绘制的字符），
由 `scripts/build_ui_font.py` 在 PC 侧用它烘出字模 JSON。
板端只读 JSON，不装字体。

**新增任何界面文字时，必须同时把它加进 `UI_FONT_TEXT` 并重跑烘字脚本**，
否则绘制时 `_text()` 会抛 `ValueError`（故意不静默跳过，避免出现空白字）。

## 性能设计

菜单是静态的（只有选中项变化）。因此：

    MenuScreen 初始化时把两种选中状态各渲染一次 → 缓存
    主循环里 `vout.writeframe(screen.frame(index))` 零开销

不需要每帧重绘文字。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# 字符集：所有界面可能用到的字符（单一来源，烘字模时直接引用）
# ---------------------------------------------------------------------------
UI_FONT_TEXT = (
    # 标题与菜单
    '皮肤病变风险预筛终端请选择工作模式一二仅评估并保存'
    '检测画面质量给出状态后方抓拍设备到'
    '确认继续退出返回菜单已存上限张剩余'
    # 运行状态
    '通过拒绝稳定中等待统计无有效结果'
    '亮度清晰度连续合格帧'
    '偏低偏高暗像素过多亮像素过分数低于阈门限'
    '过曝光值余秒倒计时'
    # 操作提示
    '按选择确认键上下一返回菜单请稍候'
    '—→不与两个为主么之也交什仍从以件任会传位体何依侧修做储先免全共关内写冲则初判别制前功加动化区即原发取叠只可右号各同向否含启和唯器因围固图在地块域增处复外够失头套如始字它安实容察寸就尺左带序库应底建开当录形律循必性意成或户所手才找把抛报拷指掉接提摄操收改故整文断新明是显最未本机板极构染查标校样核次正此每求污沿渲满点烘版独环现理用由界留白的目直相瞒硬碰示离种程空符第精约级纪纯线组绑绘绪缓缺置联能脚自色范行补被装要观视览记论证词试误说读调贝败足跑路跳轮输达运近这进速造避部都配里重销错长闭问阵隐集零需静非页顶项须频题颜首验默齐（）；'
    '「」丢串了但住使入其再几列刚刻压台圾垃宽将屏常幕异打持推旧景框没法流然知积类表让询道锁队陈'
    '“”冻对己注看而那际随靠'
    # 数字、字母、标点
    '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    'abcdefghijklmnopqrstuvwxyz'
    ' ··：，。、/|-_%().png'
)

UI_FONT_TITLE_TEXT = '皮肤病变风险预筛终端'

# ---------------------------------------------------------------------------
# 配色（深灰底 + 高对比白字；选中项用绿边+绿底+左侧竖条三重提示）
# ---------------------------------------------------------------------------
C_BG = (24, 26, 30)
C_TITLE = (240, 242, 245)
C_SUB = (150, 155, 165)
C_ITEM = (232, 235, 240)
C_DESC = (150, 155, 165)
C_BOX_BG = (32, 35, 41)
C_BOX_EDGE = (68, 74, 86)
C_SEL_BG = (28, 52, 42)
C_SEL_EDGE = (78, 200, 120)
C_SEL_BAR = (110, 230, 150)
C_HINT = (120, 126, 138)

# ---------------------------------------------------------------------------
# 布局（1280×720）
# ---------------------------------------------------------------------------
W, H = 1280, 720

TITLE_BASELINE = 70
SUB_BASELINE = 132

BOX_X, BOX_W, BOX_H = 140, 1000, 130
BOX_Y = (232, 392)          # 两个选项框的 y
ITEM_X_OFF = 62             # 框内文字 x 偏移（给左侧竖条留位置）
ITEM_Y_OFF = 26
DESC_Y_OFF = 76
SEL_BAR_W = 6

HINT_BASELINE = 604

# 选项文字
ITEMS = (
    ('模式一 · 仅评估', '检测画面质量并给出皮肤状态评估'),
    ('模式二 · 评估并保存', '评估通过后抓拍并保存到设备'),
)
HINT_TEXT = 'KEY0 / KEY1  选择          KEY2  确认'


# ---------------------------------------------------------------------------
# 字模加载
# ---------------------------------------------------------------------------
class FontSet:
    """一组同字号的点阵字模。"""

    def __init__(self, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        self.height = int(data['height'])
        self.pixel_size = int(data['pixel_size'])
        self.glyphs = {}
        for char, item in data['glyphs'].items():
            raw = np.frombuffer(base64.b64decode(item['bits']), dtype=np.uint8)
            bits = np.unpackbits(raw)
            w = int(item['width'])
            self.glyphs[char] = bits[:self.height * w].reshape(self.height, w).astype(bool)

    def __contains__(self, char):
        return char in self.glyphs

    def width(self, char):
        g = self.glyphs.get(char)
        return 0 if g is None else g.shape[1]

    def text_width(self, text):
        return sum(self.width(c) for c in text)


# ---------------------------------------------------------------------------
# 基础绘制（全部直接操作 numpy 数组，无 PIL 依赖）
# ---------------------------------------------------------------------------
def fill_rect(arr, x, y, w, h, color):
    arr[y:y + h, x:x + w, :3] = color


def stroke_rect(arr, x, y, w, h, color, t=2):
    arr[y:y + t, x:x + w, :3] = color
    arr[y + h - t:y + h, x:x + w, :3] = color
    arr[y:y + h, x:x + t, :3] = color
    arr[y:y + h, x + w - t:x + w, :3] = color


def draw_text(arr, font, x, y, text, color):
    """在 (x, y) 处绘制一行文字，y 为字形顶端。"""
    cx = int(x)
    for char in text:
        glyph = font.glyphs.get(char)
        if glyph is None:
            raise ValueError('UI font missing character: %r (U+%04X)' % (char, ord(char)))
        h, w = glyph.shape
        if cx + w > arr.shape[1]:
            raise ValueError('UI text exceeds frame width: %r' % text[:20])
        region = arr[y:y + h, cx:cx + w, :3]
        region[glyph] = color
        cx += w


def draw_text_center(arr, font, y, text, color):
    total = font.text_width(text)
    draw_text(arr, font, (arr.shape[1] - total) // 2, y, text, color)


# ---------------------------------------------------------------------------
# 菜单页
# ---------------------------------------------------------------------------
class MenuScreen:
    """预渲染两种选中状态，主循环直接取用缓存帧。"""

    def __init__(self, font24_path, font40_path, *, items=ITEMS, hint=HINT_TEXT):
        self.font_body = FontSet(font24_path)
        self.font_title = FontSet(font40_path)
        self.items = items
        self.hint = hint

        # 加载即校验：缺字立刻报错，不等到运行时
        self._validate()

        self.frames = [self._render(i) for i in range(len(items))]

    def _validate(self):
        need_body = set()
        need_body.update(UI_FONT_TEXT)
        for title, desc in self.items:
            need_body.update(title)
            need_body.update(desc)
        need_body.update(self.hint)

        missing = sorted(c for c in need_body if c not in self.font_body)
        if missing:
            raise ValueError(
                'body font missing %d chars: %s' % (len(missing), ''.join(missing))
            )
        missing_t = sorted(c for c in UI_FONT_TITLE_TEXT if c not in self.font_title)
        if missing_t:
            raise ValueError('title font missing chars: %s' % ''.join(missing_t))

    def _render(self, selected):
        arr = np.zeros((H, W, 4), dtype=np.uint8)
        arr[:, :, 3] = 255

        # 背景
        arr[:, :, :3] = C_BG

        # 标题
        top_pad = (self.font_title.height - self.font_title.pixel_size) // 2
        draw_text_center(arr, self.font_title, TITLE_BASELINE - top_pad,
                         UI_FONT_TITLE_TEXT, C_TITLE)

        # 副标题
        top_body = (self.font_body.height - self.font_body.pixel_size) // 2
        draw_text_center(arr, self.font_body, SUB_BASELINE - top_body,
                         '请选择工作模式', C_SUB)

        # 选项框
        for i, (title, desc) in enumerate(self.items):
            by = BOX_Y[i]
            on = (i == selected)
            fill_rect(arr, BOX_X, by, BOX_W, BOX_H, C_SEL_BG if on else C_BOX_BG)
            stroke_rect(arr, BOX_X, by, BOX_W, BOX_H,
                        C_SEL_EDGE if on else C_BOX_EDGE, t=3 if on else 2)
            if on:
                fill_rect(arr, BOX_X, by, SEL_BAR_W, BOX_H, C_SEL_BAR)

            tx = BOX_X + ITEM_X_OFF
            draw_text(arr, self.font_body, tx, by + ITEM_Y_OFF - top_body,
                      title, C_ITEM)
            draw_text(arr, self.font_body, tx, by + DESC_Y_OFF - top_body,
                      desc, C_DESC)

        # 底部提示
        draw_text_center(arr, self.font_body, HINT_BASELINE - top_body,
                         self.hint, C_HINT)
        return arr

    def frame(self, index):
        return self.frames[index % len(self.frames)]

    @property
    def count(self):
        return len(self.items)


# ---------------------------------------------------------------------------
# 本机自检 / 生成样图
# ---------------------------------------------------------------------------
def _selftest(python_dir):
    python_dir = Path(python_dir)
    f24 = python_dir / 'ui_font_24.json'
    f40 = python_dir / 'ui_font_40.json'
    if not f24.exists() or not f40.exists():
        print('字模不存在，请先运行 scripts/build_ui_font.py')
        return 1

    screen = MenuScreen(f24, f40)
    print('菜单页渲染 OK，共 %d 个选项' % screen.count)
    for i in range(screen.count):
        fr = screen.frame(i)
        assert fr.shape == (H, W, 4) and fr.dtype == np.uint8
        print('  index=%d  shape=%s  唯一颜色数=%d'
              % (i, fr.shape, len(np.unique(fr[:, :, :3].reshape(-1, 3), axis=0))))

    # 保存样图（RGB，去掉 alpha）
    try:
        from PIL import Image
        out = python_dir.parent / 'build' / 'ui_menu_preview'
        out.mkdir(parents=True, exist_ok=True)
        for i in range(screen.count):
            Image.fromarray(screen.frame(i)[:, :, :3]).save(out / ('menu_%d.png' % i))
        print('样图已保存到', out)
    except ImportError:
        print('（无 PIL，跳过样图）')
    return 0


if __name__ == '__main__':
    import sys
    raise SystemExit(_selftest(Path(__file__).parent))
