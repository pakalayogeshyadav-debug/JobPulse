"""jobpulse.validation.registry — Dynamic rule registry."""

from jobpulse.logging.logger import get_logger
from jobpulse.validation.base import BaseValidationRule

logger = get_logger(__name__)


class RuleRegistry:
    """Registry to dynamically register and instantiate validation rules."""

    _rules: dict[str, type[BaseValidationRule]] = {}

    @classmethod
    def register(cls, rule_name: str):
        """Decorator to register a rule class."""

        def decorator(rule_class: type[BaseValidationRule]):
            cls._rules[rule_name] = rule_class
            return rule_class

        return decorator

    @classmethod
    def get_all_rules(cls) -> list[BaseValidationRule]:
        """Instantiate and return all registered rules."""
        rules = []
        for name, rule_class in cls._rules.items():
            try:
                rules.append(rule_class())
            except Exception as e:
                logger.error(f"Failed to instantiate rule {name}: {e}")
        return rules
