import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ResearchMate.settings')
import django
django.setup()
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from papers.models import Paper, AIAnalysis
from papers.services import extract_pdf_content, process_mock_ai
from io import BytesIO
from reportlab.pdfgen import canvas

user = User.objects.create_user(username='diaguser3', password='Secret123')
buffer = BytesIO()
c = canvas.Canvas(buffer)
c.drawString(72, 720, 'Diagnosis content for start learning')
c.save()
paper = Paper.objects.create(owner=user, title='Diagnosis Paper', pdf_file=SimpleUploadedFile('diagnosis.pdf', buffer.getvalue(), content_type='application/pdf'))
print('paper created', paper.id)
content = extract_pdf_content(paper)
print('extracted_text_len', len(content.extracted_text))
try:
    process_mock_ai(paper)
    print('process succeeded')
except Exception as exc:
    import traceback
    print('EXC', repr(exc))
    traceback.print_exc()
    analysis = AIAnalysis.objects.get(paper=paper)
    print('analysis_status', analysis.analysis_status)
    print('analysis_error', analysis.analysis_error)
    print('raw_response', analysis.raw_response[:500])
