from django import template

register = template.Library()

@register.filter
def days_between(value, arg):
    """Return the number of days between two datetime/date values."""
    if value and arg:
        delta = arg - value
        return delta.days
    return None
