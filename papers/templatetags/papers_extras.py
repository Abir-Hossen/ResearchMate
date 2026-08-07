from django import template

from papers.utils import render_beginner_markdown

register = template.Library()


@register.filter(name='render_beginner_markdown')
def render_beginner_markdown_filter(value):
    return render_beginner_markdown(value)
