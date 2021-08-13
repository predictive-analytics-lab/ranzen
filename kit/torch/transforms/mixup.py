from __future__ import annotations
from enum import Enum, auto
from typing import cast, overload

import torch
from torch import Tensor
import torch.distributions as td
import torch.nn.functional as F

from kit.misc import str_to_enum

__all__ = [
    "BernoulliMixUp",
    "BetaMixUp",
    "MixUpMode",
    "RandomMixUp",
    "UniformMixUp",
]


class MixUpMode(Enum):

    linear = auto()
    geometric = auto()


class RandomMixUp:
    r"""Apply MixUp augmentation to a batch of tensors.

    Implemention for `mixup: BEYOND EMPIRICAL RISK MINIMIZATION`.
    This implementation allows for transformation of the the input in the absence
    of labels -- this is relevant for contrastive methods that use mixup to generate
    different views of samples for instance-distance discrimination -- and additionally
    allows for the interchange of different lambda samplers and of different methods for
    mixing up samples (linear vs geometric) based on lambda.

    Note:
        This implementation randomly mixes images within a batch.
    """

    def __init__(
        self,
        lambda_sampler: td.Beta | td.Uniform | td.Bernoulli,
        mode: MixUpMode | str = MixUpMode.linear,
        p: float = 1.0,
        num_classes: int | None = None,
    ) -> None:
        super().__init__()
        self.lambda_sampler = lambda_sampler
        if not 0 <= p <= 1:
            raise ValueError("'p' must be in the range [0, 1].")
        self.p = p
        if isinstance(mode, str):
            mode = str_to_enum(str_=mode, enum=MixUpMode)
        self.mode = mode
        if (num_classes is not None) and num_classes < 1:
            raise ValueError(f"{ num_classes } must be greater than 1.")
        self.num_classes = num_classes

    def _mix(self, tensor_a, *, tensor_b, lambda_) -> Tensor:
        lambda_c = 1 - lambda_
        if self.mode is MixUpMode.linear:
            return lambda_ * tensor_a + lambda_c * tensor_b
        return tensor_a ** lambda_ * tensor_b ** lambda_c

    @overload
    def transform(self, inputs: Tensor, *, targets: Tensor) -> dict[str, Tensor]:
        ...

    @overload
    def transform(self, inputs: Tensor, *, targets: None) -> Tensor:
        ...

    def transform(self, inputs: Tensor, *, targets: Tensor | None) -> Tensor | dict[str, Tensor]:
        batch_size = len(inputs)
        if self.p == 0:
            if targets is None:
                return inputs
            return dict(inputs=inputs, targets=targets)
        elif self.p < 1:
            # Sample a mask determining which samples in the batch are to be transformed
            selected = torch.rand(batch_size, device=inputs.device) < self.p
            num_selected = int(selected.count_nonzero())
            indices = selected.nonzero(as_tuple=False).long().flatten()
        # if p >= 1 then the transform is always applied and we can skip
        # the above step
        else:
            num_selected = batch_size
            indices = torch.arange(batch_size, device=inputs.device, dtype=torch.long)
        # Sample the mixup pairs with the guarantee that a given sample will
        # not be paired with itself
        offset = torch.randint(
            low=1, high=batch_size, size=(num_selected,), device=inputs.device, dtype=torch.long
        )
        pair_indices = (indices + offset) % batch_size
        # Sample the mixup interpolation parameters
        lambdas = self.lambda_sampler.sample(
            sample_shape=(num_selected, *((1,) * (inputs.ndim - 1)))
        ).to(inputs.device)
        lambdas_tiled = lambdas.view(num_selected, *((1,) * (inputs.ndim - 1)))

        inputs = inputs.clone()
        inputs[indices] = self._mix(
            tensor_a=inputs[indices], tensor_b=inputs[pair_indices], lambda_=lambdas_tiled
        )

        if targets is None:
            return inputs

        elif self.num_classes is not None:
            targets = cast(Tensor, F.one_hot(targets, num_classes=self.num_classes).float())
            lambdas_tiled = lambdas.view(num_selected, *((1,) * (targets.ndim - 1)))
            targets[indices] = self._mix(
                tensor_a=targets[indices], tensor_b=targets[pair_indices], lambda_=lambdas_tiled
            )
            return dict(inputs=inputs, targets=targets)
        raise ValueError("Mixup can only be applied to targets if 'num_classes' is specified.")

    @overload
    def __call__(self, inputs: Tensor, *, targets: Tensor) -> dict[str, Tensor]:
        ...

    @overload
    def __call__(self, inputs: Tensor, *, targets: None) -> Tensor:
        ...

    def __call__(self, inputs: Tensor, *, targets: Tensor | None) -> Tensor | dict[str, Tensor]:
        return self.transform(inputs=inputs, targets=targets)


class BetaMixUp:
    def __new__(
        cls,
        alpha: float = 0.2,
        beta: float | None = None,
        mode: MixUpMode | str = MixUpMode.linear,
        p: float = 1.0,
        num_classes: int | None = None,
    ) -> RandomMixUp:
        beta = alpha if beta is None else beta
        lambda_sampler = td.Beta(concentration0=alpha, concentration1=beta)
        return RandomMixUp(lambda_sampler=lambda_sampler, mode=mode, p=p, num_classes=num_classes)


class UniformMixUp:
    def __new__(
        cls,
        low: float = 0.0,
        high: float = 1.0,
        mode: MixUpMode | str = MixUpMode.linear,
        p: float = 1.0,
        num_classes: int | None = None,
    ) -> RandomMixUp:
        lambda_sampler = td.Uniform(low=low, high=high)
        return RandomMixUp(lambda_sampler=lambda_sampler, mode=mode, p=p, num_classes=num_classes)


class BernoulliMixUp:
    def __new__(
        cls,
        prob_1: float = 0.5,
        mode: MixUpMode | str = MixUpMode.linear,
        p: float = 1.0,
        num_classes: int | None = None,
    ) -> RandomMixUp:
        lambda_sampler = td.Bernoulli(probs=prob_1)
        return RandomMixUp(lambda_sampler=lambda_sampler, mode=mode, p=p, num_classes=num_classes)