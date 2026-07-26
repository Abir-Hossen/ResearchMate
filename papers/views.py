from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import PaperUploadForm


@login_required(login_url='login')
def upload_paper_view(request):
    if request.method == 'POST':
        form = PaperUploadForm(request.POST, request.FILES)
        if form.is_valid():
            paper = form.save(commit=False)
            paper.owner = request.user
            paper.save()
            messages.success(request, 'Paper uploaded successfully.')
            return redirect('dashboard')
    else:
        form = PaperUploadForm()

    return render(request, 'papers/upload.html', {'form': form})
