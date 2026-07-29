import os
from io import BytesIO

import django
from reportlab.pdfgen import canvas
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ResearchMate.settings')
django.setup()

from django.conf import settings
from papers.models import Paper
from papers.services import extract_pdf_content, process_mock_ai

print('DJANGO SETTINGS MODULE:', os.environ.get('DJANGO_SETTINGS_MODULE'))
print('PYTHON EXECUTABLE:', os.path.abspath(__file__))
print('settings.GEMINI_API_KEY:', repr(settings.GEMINI_API_KEY))
print('GEMINI_ENV:', repr(os.environ.get('GEMINI_API_KEY')))

user, _ = User.objects.get_or_create(username='debuguser')
buffer = BytesIO()
pdf_canvas = canvas.Canvas(buffer)
pdf_canvas.drawString(72, 720, 'debugging test')
pdf_canvas.save()
pdf_bytes = buffer.getvalue()
paper = Paper.objects.create(owner=user, title='Debug Paper', pdf_file=SimpleUploadedFile('debug.pdf', pdf_bytes, content_type='application/pdf'))
print('paper created:', paper.pk)

try:
    content = extract_pdf_content(paper)
    print('content status:', content.extraction_status)
    print('content len:', len(content.extracted_text))
except Exception as e:
    import traceback
    print('extract error:')
    traceback.print_exc()

try:
    analysis = process_mock_ai(paper)
    print('analysis returned:', analysis)
    try:
        ai = paper.ai_analysis
        print('paper.ai_analysis.status', ai.analysis_status)
        print('overview', repr(ai.overview))
    except Exception as e:
        print('no analysis object', e)
except Exception as e:
    import traceback
    print('process_mock_ai error:')
    traceback.print_exc()
