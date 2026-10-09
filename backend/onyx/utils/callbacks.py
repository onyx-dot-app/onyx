from typing import Generic, TypeVar

T = TypeVar("T")


class MetricsHander(Generic[T]):
    def __init__(self) -> None:
        self.metrics: T | None = None

    def record_metric(self, metrics: T) -> None:
        self.metrics = metrics
