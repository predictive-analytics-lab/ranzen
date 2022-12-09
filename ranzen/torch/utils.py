from __future__ import annotations
from collections.abc import Iterable, Iterator
from datetime import datetime
import random
from typing import Any, List, TypeVar

import numpy as np
import torch
from torch import Tensor
import torch.nn as nn

__all__ = ["count_parameters", "random_seed", "inf_generator", "Event", "batchwise_pdist"]


def count_parameters(model: nn.Module) -> int:
    """Count all parameters (that have a gradient) in the given model"""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def random_seed(seed_value: int, *, use_cuda: bool) -> None:
    np.random.seed(seed_value)  # cpu vars
    torch.manual_seed(seed_value)  # cpu  vars
    random.seed(seed_value)  # Python
    if use_cuda:
        torch.cuda.manual_seed(seed_value)
        torch.cuda.manual_seed_all(seed_value)
        torch.backends.cudnn.deterministic = True  # type: ignore
        torch.backends.cudnn.benchmark = False  # type: ignore


T = TypeVar("T")


def inf_generator(iterable: Iterable[T]) -> Iterator[T]:
    """Get DataLoaders in a single infinite loop.

    for i, (x, y) in enumerate(inf_generator(train_loader))
    """
    iterator = iter(iterable)
    # try to take one element to ensure that the iterator is not empty
    first_value = next(iterator, None)
    if first_value is not None:
        yield first_value
    else:
        raise RuntimeError("The given iterable is empty.")
    while True:
        try:
            yield next(iterator)
        except StopIteration:
            iterator = iter(iterable)


class Event:
    """Emulates torch.cuda.Event, but supports running on a CPU too.

    :example:
        >>> from ranzen.torch import Event
        >>> with Event() as event:
        >>>     y = some_nn_module(x)
        >>> print(event.time)
    """

    def __init__(self) -> None:
        self.time = 0.0
        self._cuda = torch.cuda.is_available()
        self._event_start: torch.cuda.Event | datetime

    def __enter__(self) -> Event:
        """Mark a time.

        Mimics torch.cuda.Event.
        """
        if self._cuda:
            self._event_start = torch.cuda.Event(enable_timing=True)
            self._event_start.record()
        else:
            self._event_start = datetime.now()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._cuda:
            event_end = torch.cuda.Event(enable_timing=True)
            event_end.record(stream=torch.cuda.current_stream())
            torch.cuda.synchronize()
            assert isinstance(self._event_start, torch.cuda.Event)
            self.time = self._event_start.elapsed_time(event_end)
        else:
            assert isinstance(self._event_start, datetime)
            self.time = datetime.now().microsecond - self._event_start.microsecond

    def __repr__(self) -> str:
        return f"Event of duration: {self.time}"


def batchwise_pdist(x: Tensor, chunk_size: int = 1000, p_norm: float = 2.0) -> Tensor:
    """Compute pair-wise distance in batches.

    This is sometimes necessary because if you compute pdist directly, it doesn't fit into memory.

    :param x: Tensor of shape (N, F) where F is the number of features.
    :param chunk_size: Size of the chunks that are used to compute the pair-wise distance. Larger
        chunk size is probably faster, but may not fit into memory.
    :param p_norm: Which norm to use for the distance. Euclidean norm by default.
    :returns: All pair-wise distances in a tensor of shape (N, N).
    """
    chunks = torch.split(x, chunk_size)

    columns: List[Tensor] = []
    for chunk in chunks:
        shards = [torch.cdist(chunk, other_chunk, p_norm) for other_chunk in chunks]
        column = torch.cat(shards, dim=1)
        # the result has to be moved to the CPU; otherwise we'll run out of GPU memory
        columns.append(column.cpu())

        # free up memory
        for shard in shards:
            del shard
        del column
        torch.cuda.empty_cache()

    dist = torch.cat(columns, dim=0)

    # free up memory
    for column in columns:
        del column
    torch.cuda.empty_cache()
    return dist
