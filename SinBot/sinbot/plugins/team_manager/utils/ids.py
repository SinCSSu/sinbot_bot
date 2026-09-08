"""自实现标准 Snowflake ID 生成器。

位布局（共 63 bit，最高位恒 0，保证落在 int64 / SQLite INTEGER 范围内）：

| 字段      | 位数 | 说明                                   |
|-----------|------|----------------------------------------|
| 时间戳    | 41   | 相对 epoch 的毫秒数，约可覆盖 69 年     |
| worker_id | 10   | 实例号 0~1023，多机/多进程部署时分配    |
| sequence  | 12   | 同一毫秒内自增序列 0~4095              |

线程安全：内部使用 threading.Lock。
时钟回拨：直接抛异常兜底，避免产生重复 ID。
"""

import threading
import time

_EPOCH_MS = 1_577_836_800_000  # 2020-01-01 00:00:00 UTC，41 bit 毫秒可覆盖至 ~2089
_WORKER_BITS = 10
_SEQ_BITS = 12
_WORKER_MASK = (1 << _WORKER_BITS) - 1
_SEQ_MASK = (1 << _SEQ_BITS) - 1
_TS_SHIFT = _WORKER_BITS + _SEQ_BITS


class SnowflakeID:
    def __init__(self, worker_id: int = 0, epoch_ms: int = _EPOCH_MS) -> None:
        if not 0 <= worker_id <= _WORKER_MASK:
            raise ValueError(f"worker_id 必须在 [0, {_WORKER_MASK}] 内")
        self._epoch = epoch_ms
        self._worker = worker_id << _SEQ_BITS
        self._seq = 0
        self._last_ms = -1
        self._lock = threading.Lock()

    def next_id(self) -> int:
        with self._lock:
            ms = int(time.time() * 1000) - self._epoch
            if ms < self._last_ms:
                raise RuntimeError("检测到系统时钟回拨，拒绝生成可能重复的 ID")
            if ms == self._last_ms:
                self._seq = (self._seq + 1) & _SEQ_MASK
                if self._seq == 0:  # 同一毫秒内序列耗尽，自旋等待下一毫秒
                    while ms <= self._last_ms:
                        ms = int(time.time() * 1000) - self._epoch
            else:
                self._seq = 0
            self._last_ms = ms
            return (ms << _TS_SHIFT) | self._worker | self._seq


# 单 bot 单进程场景 worker_id=0 即可；多机部署时给每台配不同的 0~1023
_gen = SnowflakeID(worker_id=0)


def next_id() -> int:
    """生成下一个雪花 ID（63 bit 正整数，可作为 BIGINT 主键）。"""
    return _gen.next_id()
