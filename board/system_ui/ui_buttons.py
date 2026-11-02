# -*- coding: utf-8 -*-
"""板上 4 个用户按键的去抖与边沿检测。

## 为什么极性做成可配置

`btns_gpio` 这个 IP 虽然存在于 overlay，但**从未在本项目中被读取过**，
按下时读到的是 1 还是 0 尚未实测。因此本模块不猜极性：

    Buttons(active_low=False)   # 按下 = 1（PYNQ 常见）
    Buttons(active_low=True)    # 按下 = 0（上拉 + 接地按键）

上板第一步应先打印原始值确认，再把正确的极性传进来。
`Buttons.describe_raw()` 就是给这一步用的。

## 去抖策略

每个键独立维护「连续相同原始值的次数」。连续 `debounce` 次相同才更新稳定状态，
稳定状态由「未按下」变「按下」时报告一次按下（不会连发）。

默认 debounce=3、轮询周期约 10~20 ms → 去抖窗口 30~60 ms，覆盖常见机械抖动。

## 不依赖 PYNQ

`poll()` 只接收一个 0..15 的整数，因此本机可以用合成序列做单元测试。
真正读硬件由调用方负责（见 `read_raw()`）。
"""

from __future__ import annotations

import time

KEY_NAMES = ('KEY0', 'KEY1', 'KEY2', 'KEY3')


class Buttons:
    """4 键去抖 + 按下边沿检测。"""

    def __init__(self, *, active_low=False, debounce=3, n_keys=4):
        if debounce < 1:
            raise ValueError('debounce 必须 >= 1')
        if not 1 <= n_keys <= 8:
            raise ValueError('n_keys 必须在 1..8')
        self.active_low = bool(active_low)
        self.debounce = int(debounce)
        self.n_keys = int(n_keys)
        self._raw = 0
        self._count = [0] * self.n_keys
        self._stable = 0          # 稳定状态位图：1 = 按下
        self._last_seen = 0       # 上一次原始位图（已归一到「按下=1」）

    # -- 内部：把原始位图归一成「按下=1」 ---------------------------------
    def _normalize(self, raw):
        raw = int(raw) & ((1 << self.n_keys) - 1)
        if self.active_low:
            raw ^= (1 << self.n_keys) - 1
        return raw

    # -- 主接口 ----------------------------------------------------------
    def poll(self, raw):
        """喂入一次原始读数，返回本次**新按下**的键索引列表。"""
        norm = self._normalize(raw)
        self._raw = int(raw)
        pressed = []
        for i in range(self.n_keys):
            bit = (norm >> i) & 1
            if bit == self._last_seen_bit(i):
                self._count[i] = min(self._count[i] + 1, self.debounce)
            else:
                self._count[i] = 1
            if self._count[i] >= self.debounce:
                was = (self._stable >> i) & 1
                if bit and not was:
                    pressed.append(i)
                if bit:
                    self._stable |= (1 << i)
                else:
                    self._stable &= ~(1 << i)
        self._last_seen = norm
        return pressed

    def _last_seen_bit(self, i):
        return (self._last_seen >> i) & 1

    # -- 查询 ------------------------------------------------------------
    @property
    def stable_mask(self):
        """当前去抖后的稳定状态位图（1 = 按下）。"""
        return self._stable

    def is_down(self, index):
        return bool((self._stable >> index) & 1)

    def down_keys(self):
        return [KEY_NAMES[i] for i in range(self.n_keys) if self.is_down(i)]

    def reset(self):
        self._count = [0] * self.n_keys
        self._stable = 0
        self._last_seen = 0

    # -- 诊断 ------------------------------------------------------------
    def describe_raw(self):
        return 'raw=0b%04b  按下位=%s' % (
            self._raw & 0xF,
            ''.join(str((self._normalize(self._raw) >> i) & 1) for i in range(self.n_keys)),
        )


# ---------------------------------------------------------------------------
# 硬件读取（仅在板端 import pynq 成功时可用）
# ---------------------------------------------------------------------------
def read_raw(gpio):
    """从 PYNQ 的 btns_gpio 对象读一次原始掩码。

    gpio 可以是 `ol.btns_gpio`，也可以是 `.channel1`。
    """
    if hasattr(gpio, 'read'):
        try:
            return int(gpio.read())
        except TypeError:
            return int(gpio.read(0))
    raise TypeError('无法识别的 gpio 对象，需要带 read() 方法')


# ---------------------------------------------------------------------------
# 后台按键轮询线程
# ---------------------------------------------------------------------------
class ButtonPoller:
    """独立线程以固定周期读按键，把按下事件排队。

    ## 为什么需要线程

    主循环里 writeframe() 会阻塞等 DMA（约 27 ms），加上 sleep，
    一轮迭代可能 40 ms。而去抖需要连续 N 次采样，
    3 次 x 40 ms = 120 ms —— 按得快一点就被整体漏掉。

    改成后台线程每 4 ms 读一次按键，去抖 3 次只需 12 ms，
    主循环再从队列里取事件，按键就不会丢。

    ## 用法

        poller = ButtonPoller(gpio, Buttons(active_low=False, debounce=3))
        poller.start()
        ...
        for key in poller.drain():
            handle(key)
        ...
        poller.stop()
    """

    def __init__(self, gpio, buttons, *, poll_s=0.004):
        import threading
        from collections import deque
        self._threading = threading
        self._deque = deque
        self._gpio = gpio
        self._buttons = buttons
        self._poll_s = max(0.001, float(poll_s))
        self._events = deque()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self.reads = 0
        self.errors = 0

    def start(self):
        if self._thread is not None:
            return
        self._thread = self._threading.Thread(
            target=self._run, name='btn-poller', daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                raw = read_raw(self._gpio)
                self.reads += 1
                pressed = self._buttons.poll(raw)
            except Exception:
                self.errors += 1
                pressed = []
            if pressed:
                with self._lock:
                    self._events.extend(pressed)
            time.sleep(self._poll_s)

    def drain(self):
        """取出并清空自上次调用以来累积的按下事件。"""
        with self._lock:
            out = list(self._events)
            self._events.clear()
        return out

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False


# ---------------------------------------------------------------------------
# 自检：本机用合成序列验证去抖与边沿
# ---------------------------------------------------------------------------
def _selftest():
    print('=' * 66)
    print('按键去抖自检')
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

    # 1. 按下沿检测（按下=1）
    b = Buttons(active_low=False, debounce=3)
    seq = [0, 0, 0, 1, 1, 1, 1, 0, 0, 0]
    got = []
    for raw in seq:
        got += b.poll(raw)
    check('按下=1 时检测到 KEY0 一次', got == [0])

    # 2. 长按不连发
    b = Buttons(active_low=False, debounce=3)
    got = []
    for _ in range(20):
        got += b.poll(1)
    check('长按不连发', got == [0])

    # 3. 抖动被过滤
    b = Buttons(active_low=False, debounce=3)
    got = []
    for raw in [0, 1, 0, 1, 0, 0, 0]:
        got += b.poll(raw)
    check('抖动不产生按下', got == [])
    check('抖动后仍为未按下', b.stable_mask == 0)

    # 4. active_low 极性
    b = Buttons(active_low=True, debounce=2)
    got = []
    for raw in [0xF, 0xE, 0xE, 0xE]:
        got += b.poll(raw)
    check('active_low 时 0 位下降沿算按下', got == [0])

    # 5. 多键同时按下
    b = Buttons(active_low=False, debounce=2)
    got = []
    for raw in [0, 0x5, 0x5]:
        got += b.poll(raw)
    check('同时按下 KEY0+KEY2', sorted(got) == [0, 2])

    # 6. 默认状态下不误报
    b = Buttons(active_low=False, debounce=3)
    got = []
    for _ in range(10):
        got += b.poll(0)
    check('全松开不误报', got == [])

    print()
    print('结果: %d 通过 / %d 失败' % (ok, fail))
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    raise SystemExit(_selftest())
