from __future__ import annotations

from abc import ABC, abstractmethod

from io_guard.types import Evidence, GuardRequest


class Detector(ABC):
    name: str

    @abstractmethod
    def detect(self, request: GuardRequest) -> list[Evidence]:
        raise NotImplementedError
