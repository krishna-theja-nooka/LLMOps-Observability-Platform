import math
import time
from collections import OrderedDict, deque


class CircuitOpen(Exception):
    pass


class CircuitBreaker:
    """One worker/event loop; failures count exhausted logical model calls."""

    def __init__(self, threshold: int, reset_s: float, clock=time.monotonic):
        self.threshold = threshold
        self.reset_s = reset_s
        self.clock = clock
        self.failures = 0
        self.opened_at: float | None = None
        self.probing = False
        self.epoch = 0

    @property
    def state(self):
        if self.probing:
            return "half_open"
        return "open" if self.opened_at is not None else "closed"

    def acquire(self):
        if self.opened_at is None:
            return False
        if self.probing or self.clock() - self.opened_at < self.reset_s:
            raise CircuitOpen()
        self.probing = True
        return True

    def success(self, epoch=None):
        if epoch is not None and epoch != self.epoch:
            return
        if self.opened_at is not None:
            self.epoch += 1
        self.failures = 0
        self.opened_at = None
        self.probing = False

    def failure(self, epoch=None):
        if epoch is not None and epoch != self.epoch:
            return False
        self.failures += 1
        opened = self.probing or self.failures >= self.threshold
        if opened:
            self.opened_at = self.clock()
            self.epoch += 1
        self.probing = False
        return opened

    def cancel_probe(self):
        self.probing = False


class RateLimiter:
    def __init__(self, limit: int, window_s: float, capacity: int, clock=time.monotonic):
        self.limit, self.window_s, self.capacity, self.clock = limit, window_s, capacity, clock
        self.clients: dict[str, deque] = {}

    def allow(self, client: str) -> tuple[bool, int]:
        now = self.clock()
        for key in list(self.clients):
            bucket = self.clients[key]
            while bucket and bucket[0] <= now - self.window_s:
                bucket.popleft()
            if not bucket:
                del self.clients[key]
        if client not in self.clients and len(self.clients) >= self.capacity:
            # Do not evict active clients, which would allow quota bypass.
            return False, math.ceil(self.window_s)
        bucket = self.clients.setdefault(client, deque())
        if len(bucket) >= self.limit:
            return False, max(1, math.ceil(self.window_s - (now - bucket[0])))
        bucket.append(now)
        return True, 0


class TTLCache:
    def __init__(self, ttl_s: float, capacity: int, clock=time.monotonic):
        self.ttl_s, self.capacity, self.clock = ttl_s, capacity, clock
        self.items: OrderedDict[str, tuple[float, object]] = OrderedDict()

    def get(self, key):
        item = self.items.get(key)
        if item is None:
            return None
        expires, value = item
        if expires <= self.clock():
            del self.items[key]
            return None
        self.items.move_to_end(key)
        return value

    def put(self, key, value):
        self.items[key] = (self.clock() + self.ttl_s, value)
        self.items.move_to_end(key)
        while len(self.items) > self.capacity:
            self.items.popitem(last=False)
