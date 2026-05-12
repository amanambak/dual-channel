from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    name: str
    meaning: str
    types: tuple[str, ...]
    enum_values: tuple[str, ...] = ()

    def prompt_description(self) -> str:
        parts = [f"type={','.join(self.types)}"]
        if self.enum_values:
            parts.append(f"allowed={','.join(self.enum_values)}")
        if self.meaning:
            parts.append(self.meaning)
        return " | ".join(parts)
