from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .kokoro import (
    DEFAULT_KOKORO_VARIANT,
    KOKORO_DISPLAY_NAME,
    KOKORO_MODEL_ID,
    KOKORO_VARIANTS,
    KokoroAdapter,
)
from .model import ModelSelection, SpeechModel

ModelFactory = Callable[[ModelSelection], SpeechModel]


@dataclass(frozen=True)
class RegisteredModel:
    model_id: str
    display_name: str
    variants: tuple[str, ...]
    default_variant: str
    factory: ModelFactory

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("Registered model identity must not be empty")
        if not self.variants:
            raise ValueError(f"Registered model '{self.model_id}' needs a variant")
        if self.default_variant not in self.variants:
            raise ValueError(
                f"Default variant '{self.default_variant}' is not registered "
                f"for model '{self.model_id}'"
            )


class ModelRegistry:
    """Resolve public model names to validated adapter instances."""

    def __init__(
        self,
        registrations: Iterable[RegisteredModel],
        *,
        default_model_id: str,
    ) -> None:
        self._models: dict[str, RegisteredModel] = {}
        for registration in registrations:
            if registration.model_id in self._models:
                raise ValueError(
                    f"Model identity '{registration.model_id}' is registered twice"
                )
            self._models[registration.model_id] = registration
        if default_model_id not in self._models:
            raise ValueError(f"Default model '{default_model_id}' is not registered")
        self.default_model_id = default_model_id

    @property
    def registrations(self) -> tuple[RegisteredModel, ...]:
        return tuple(self._models.values())

    @property
    def model_ids(self) -> tuple[str, ...]:
        return tuple(self._models)

    def select(
        self, model_id: str | None = None, variant: str | None = None
    ) -> ModelSelection:
        selected_model_id = model_id or self.default_model_id
        try:
            registration = self._models[selected_model_id]
        except KeyError as error:
            choices = ", ".join(self.model_ids)
            raise ValueError(
                f"Unknown model identity '{selected_model_id}'. Choose one of: {choices}"
            ) from error
        selected_variant = variant or registration.default_variant
        if selected_variant not in registration.variants:
            choices = ", ".join(registration.variants)
            raise ValueError(
                f"Unknown {selected_model_id} variant '{selected_variant}'. "
                f"Choose one of: {choices}"
            )
        return ModelSelection(selected_model_id, selected_variant)

    def create(self, selection: ModelSelection) -> SpeechModel:
        validated = self.select(selection.model_id, selection.variant)
        return self._models[validated.model_id].factory(validated)


MODEL_REGISTRY = ModelRegistry(
    (
        RegisteredModel(
            model_id=KOKORO_MODEL_ID,
            display_name=KOKORO_DISPLAY_NAME,
            variants=KOKORO_VARIANTS,
            default_variant=DEFAULT_KOKORO_VARIANT,
            factory=KokoroAdapter,
        ),
    ),
    default_model_id=KOKORO_MODEL_ID,
)
