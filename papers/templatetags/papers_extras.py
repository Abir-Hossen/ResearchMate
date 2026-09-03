from django import template

from papers.utils import render_beginner_markdown

register = template.Library()


@register.filter(name='render_beginner_markdown')
def render_beginner_markdown_filter(value):
    return render_beginner_markdown(value)


@register.filter(name='premium_badge_class')
def premium_badge_class_filter(is_premium):
    return 'bg-success text-white' if is_premium else 'bg-warning text-dark'
