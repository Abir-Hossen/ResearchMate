from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from .decorators import staff_required
from .forms import AdminLoginForm, AdminPasswordResetForm, AdminUserEditForm


User = get_user_model()


def admin_login_view(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('admin_panel:home')
        return redirect('home')

    if request.method == 'POST':
        form = AdminLoginForm(request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            next_url = request.POST.get('next') or request.GET.get('next') or ''
            if next_url and next_url.startswith('/admin-panel/'):
                return redirect(next_url)
            return redirect('admin_panel:home')
    else:
        form = AdminLoginForm()

    return render(request, 'admin_panel/login.html', {'form': form})


def admin_logout_view(request):
    logout(request)
    messages.success(request, 'You have been logged out of the admin panel.')
    return redirect('admin_panel:login')


@staff_required
def admin_change_password_view(request):
    from django.contrib.auth.forms import PasswordChangeForm

    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, user)
            messages.success(request, 'Your admin password has been changed successfully.')
            return redirect('admin_panel:home')
    else:
        form = PasswordChangeForm(request.user)

    return render(request, 'admin_panel/profile/change_password.html', {'form': form})


@staff_required
def admin_panel_home(request):
    from papers.models import Paper, AIAnalysis
    from subscriptions.models import PaymentTransaction, UserSubscription

    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()

    total_papers = Paper.objects.count()
    papers_uploaded = Paper.objects.filter(processing_status='Uploaded').count()
    papers_processing = Paper.objects.filter(processing_status='Processing').count()
    papers_completed = Paper.objects.filter(processing_status='Completed').count()

    total_ai_analyses = AIAnalysis.objects.count()
    failed_ai_analyses = AIAnalysis.objects.filter(analysis_status='Failed').count()
    ready_ai_analyses = AIAnalysis.objects.filter(analysis_status='Ready').count()

    active_subscriptions = UserSubscription.objects.filter(status='ACTIVE').count()

    successful_payments = PaymentTransaction.objects.filter(status='SUCCESS').count()
    revenue = PaymentTransaction.objects.filter(status='SUCCESS').aggregate(total=Sum('amount'))['total'] or 0

    metrics = {
        'total_users': total_users,
        'active_users': active_users,
        'total_papers': total_papers,
        'papers_uploaded': papers_uploaded,
        'papers_processing': papers_processing,
        'papers_completed': papers_completed,
        'total_ai_analyses': total_ai_analyses,
        'failed_ai_analyses': failed_ai_analyses,
        'ready_ai_analyses': ready_ai_analyses,
        'active_subscriptions': active_subscriptions,
        'successful_payments': successful_payments,
        'total_revenue': revenue,
    }

    return render(request, 'admin_panel/dashboard.html', {'metrics': metrics})


@staff_required
def user_list(request):
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all').lower()
    staff_filter = request.GET.get('staff', 'all').lower()

    users = User.objects.all().annotate(
        paper_count=Count('papers')
    ).order_by('-date_joined')

    if query:
        users = users.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )

    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)

    if staff_filter == 'staff':
        users = users.filter(is_staff=True)
    elif staff_filter == 'non-staff':
        users = users.filter(is_staff=False)

    paginator = Paginator(users, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'admin_panel/users/list.html', {
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
        'staff_filter': staff_filter,
    })


@staff_required
def user_detail(request, user_id):
    user_obj = get_object_or_404(User, pk=user_id)

    papers = user_obj.papers.select_related('content', 'ai_analysis', 'learning_progress').prefetch_related(
        'glossary_terms', 'flashcards', 'quiz_questions', 'viva_questions', 'section_learning_sections', 'quiz_attempts'
    ).order_by('-uploaded_at')

    subscriptions = user_obj.subscriptions.select_related('plan').order_by('-created_at')
    payments = user_obj.payment_transactions.select_related('plan').order_by('-created_at')
    reviews = user_obj.reviews.order_by('-created_at')

    return render(request, 'admin_panel/users/detail.html', {
        'user_obj': user_obj,
        'papers': papers,
        'subscriptions': subscriptions,
        'payments': payments,
        'reviews': reviews,
    })


@staff_required
def toggle_user_active(request, user_id):
    if request.method != 'POST':
        return redirect('admin_panel:user_list')

    user_obj = get_object_or_404(User, pk=user_id)

    if user_obj == request.user:
        messages.error(request, 'You cannot deactivate your own account.')
        return redirect('admin_panel:user_detail', user_id=user_obj.id)

    user_obj.is_active = not user_obj.is_active
    user_obj.save(update_fields=['is_active'])

    if user_obj.is_active:
        messages.success(request, f'User {user_obj.username} has been activated.')
    else:
        messages.warning(request, f'User {user_obj.username} has been deactivated.')

    return redirect('admin_panel:user_detail', user_id=user_obj.id)


@staff_required
def user_edit(request, user_id):
    user_obj = get_object_or_404(User, pk=user_id)

    if request.method == 'POST':
        form = AdminUserEditForm(request.POST, instance=user_obj)
        if form.is_valid():
            form.save()
            messages.success(request, f'User {user_obj.username} has been updated.')
            return redirect('admin_panel:user_detail', user_id=user_obj.id)
    else:
        form = AdminUserEditForm(instance=user_obj)

    return render(request, 'admin_panel/users/edit.html', {
        'user_obj': user_obj,
        'form': form,
    })


@staff_required
def user_reset_password(request, user_id):
    user_obj = get_object_or_404(User, pk=user_id)

    if request.method == 'POST':
        form = AdminPasswordResetForm(request.POST)
        if form.is_valid():
            form.save(user_obj)
            messages.success(request, f'Password has been reset for {user_obj.username}.')
            return redirect('admin_panel:user_detail', user_id=user_obj.id)
    else:
        form = AdminPasswordResetForm()

    return render(request, 'admin_panel/users/reset_password.html', {
        'user_obj': user_obj,
        'form': form,
    })


@staff_required
def paper_list(request):
    from papers.models import Paper

    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all')

    papers = Paper.objects.select_related('owner', 'ai_analysis', 'content', 'learning_progress').annotate(
        quiz_question_count=Count('quiz_questions', distinct=True),
        viva_question_count=Count('viva_questions', distinct=True),
        section_count=Count('section_learning_sections', distinct=True),
    ).order_by('-uploaded_at')

    if query:
        papers = papers.filter(
            Q(title__icontains=query) |
            Q(owner__username__icontains=query) |
            Q(owner__email__icontains=query)
        )

    valid_statuses = ['Uploaded', 'Processing', 'Completed']
    if status_filter in valid_statuses:
        papers = papers.filter(processing_status=status_filter)

    paginator = Paginator(papers, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'admin_panel/papers/list.html', {
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
    })


@staff_required
def paper_detail(request, paper_id):
    from papers.models import Paper
    from papers.dashboard_service import get_completion_percentage

    paper = get_object_or_404(
        Paper.objects.select_related('owner', 'content', 'ai_analysis', 'learning_progress'),
        pk=paper_id
    )

    glossary_terms = paper.glossary_terms.all().order_by('display_order', 'id')[:100]
    flashcards = paper.flashcards.all().order_by('display_order', 'id')[:100]
    quiz_questions = paper.quiz_questions.all().order_by('display_order', 'id')[:100]
    quiz_attempts = paper.quiz_attempts.all().order_by('-completed_at')[:50]
    viva_questions = paper.viva_questions.all().order_by('display_order', 'id')[:100]
    paper_sections = paper.section_learning_sections.all().order_by('section_order', 'id')[:100]

    completion_percentage = get_completion_percentage(paper)

    return render(request, 'admin_panel/papers/detail.html', {
        'paper': paper,
        'glossary_terms': glossary_terms,
        'flashcards': flashcards,
        'quiz_questions': quiz_questions,
        'quiz_attempts': quiz_attempts,
        'viva_questions': viva_questions,
        'paper_sections': paper_sections,
        'glossary_count': paper.glossary_terms.count(),
        'flashcard_count': paper.flashcards.count(),
        'quiz_question_count': paper.quiz_questions.count(),
        'viva_question_count': paper.viva_questions.count(),
        'section_count': paper.section_learning_sections.count(),
        'quiz_attempt_count': paper.quiz_attempts.count(),
        'completion_percentage': completion_percentage,
    })


@staff_required
def subscription_list(request):
    from subscriptions.models import UserSubscription

    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all')

    subscriptions = UserSubscription.objects.select_related('user', 'plan').order_by('-created_at')

    if query:
        subscriptions = subscriptions.filter(
            Q(user__username__icontains=query) |
            Q(user__email__icontains=query) |
            Q(plan__name__icontains=query)
        )

    valid_statuses = ['PENDING', 'ACTIVE', 'EXPIRED', 'CANCELLED']
    if status_filter in valid_statuses:
        subscriptions = subscriptions.filter(status=status_filter)

    paginator = Paginator(subscriptions, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'admin_panel/subscriptions/list.html', {
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
    })


@staff_required
def subscription_detail(request, subscription_id):
    from subscriptions.models import UserSubscription
    from subscriptions.services import user_has_premium_access

    subscription = get_object_or_404(
        UserSubscription.objects.select_related('user', 'plan'),
        pk=subscription_id
    )

    has_premium = user_has_premium_access(subscription.user)
    user_subscriptions = subscription.user.subscriptions.select_related('plan').order_by('-created_at')[:50]

    return render(request, 'admin_panel/subscriptions/detail.html', {
        'subscription': subscription,
        'has_premium': has_premium,
        'user_subscriptions': user_subscriptions,
    })


@staff_required
def grant_subscription_view(request, subscription_id):
    from subscriptions.models import SubscriptionPlan, UserSubscription
    from subscriptions.services import grant_manual_subscription

    subscription = get_object_or_404(
        UserSubscription.objects.select_related('user', 'plan'),
        pk=subscription_id
    )

    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('duration_days')

    if request.method == 'POST':
        plan_id = request.POST.get('plan_id')
        plan = SubscriptionPlan.objects.filter(pk=plan_id, is_active=True).first()
        if not plan:
            messages.error(request, 'Selected plan is not available.')
            return redirect('admin_panel:subscription_grant', subscription_id=subscription.id)

        try:
            grant_manual_subscription(subscription.user, plan)
            messages.success(
                request,
                f'Premium access granted to {subscription.user.username} for plan {plan.name}.'
            )
        except Exception as exc:
            messages.error(request, f'Unable to grant Premium access: {exc}')

        return redirect('admin_panel:subscription_detail', subscription_id=subscription.id)

    return render(request, 'admin_panel/subscriptions/grant.html', {
        'subscription': subscription,
        'plans': plans,
    })


@staff_required
def revoke_subscription_view(request, subscription_id):
    from subscriptions.models import UserSubscription
    from subscriptions.services import revoke_subscription

    subscription = get_object_or_404(
        UserSubscription.objects.select_related('user', 'plan'),
        pk=subscription_id
    )

    if request.method == 'POST':
        try:
            result = revoke_subscription(subscription.user)
            if result is None:
                messages.warning(request, f'No active subscription to revoke for {subscription.user.username}.')
            else:
                messages.success(request, f'Premium access revoked for {subscription.user.username}.')
        except Exception as exc:
            messages.error(request, f'Unable to revoke Premium access: {exc}')

        return redirect('admin_panel:subscription_detail', subscription_id=subscription.id)

    return render(request, 'admin_panel/subscriptions/revoke.html', {
        'subscription': subscription,
    })


@staff_required
def extend_subscription_view(request, subscription_id):
    from subscriptions.models import UserSubscription
    from subscriptions.services import extend_subscription

    subscription = get_object_or_404(
        UserSubscription.objects.select_related('user', 'plan'),
        pk=subscription_id
    )

    if request.method == 'POST':
        try:
            days = int(request.POST.get('days', 0))
        except (TypeError, ValueError):
            days = 0

        if days <= 0:
            messages.error(request, 'Extension days must be a positive integer.')
            return redirect('admin_panel:subscription_extend', subscription_id=subscription.id)

        try:
            extend_subscription(subscription.user, days)
            messages.success(
                request,
                f'Premium access extended by {days} day(s) for {subscription.user.username}.'
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, f'Unable to extend Premium access: {exc}')

        return redirect('admin_panel:subscription_detail', subscription_id=subscription.id)

    return render(request, 'admin_panel/subscriptions/extend.html', {
        'subscription': subscription,
    })


@staff_required
def payment_list(request):
    from subscriptions.models import PaymentTransaction

    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all')

    payments = PaymentTransaction.objects.select_related('user', 'plan').order_by('-created_at')

    if query:
        payments = payments.filter(
            Q(user__username__icontains=query) |
            Q(user__email__icontains=query) |
            Q(transaction_id__icontains=query) |
            Q(gateway_transaction_id__icontains=query) |
            Q(plan__name__icontains=query)
        )

    valid_statuses = [choice[0] for choice in PaymentTransaction.PaymentStatus.choices]
    if status_filter in valid_statuses:
        payments = payments.filter(status=status_filter)

    paginator = Paginator(payments, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'admin_panel/payments/list.html', {
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
    })


@staff_required
def payment_detail(request, payment_id):
    from subscriptions.models import PaymentTransaction

    payment = get_object_or_404(
        PaymentTransaction.objects.select_related('user', 'plan'),
        pk=payment_id
    )

    return render(request, 'admin_panel/payments/detail.html', {
        'payment': payment,
    })


@staff_required
def plan_list(request):
    from subscriptions.models import SubscriptionPlan

    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', 'all').lower()

    plans = SubscriptionPlan.objects.all().order_by('duration_days')

    if query:
        plans = plans.filter(
            Q(name__icontains=query) |
            Q(slug__icontains=query)
        )

    if status_filter == 'active':
        plans = plans.filter(is_active=True)
    elif status_filter == 'inactive':
        plans = plans.filter(is_active=False)

    return render(request, 'admin_panel/subscriptions/plans/list.html', {
        'plans': plans,
        'query': query,
        'status_filter': status_filter,
    })


@staff_required
def plan_create(request):
    from subscriptions.models import SubscriptionPlan

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        slug = request.POST.get('slug', '').strip()
        description = request.POST.get('description', '').strip()
        price = request.POST.get('price', '').strip()
        duration_days = request.POST.get('duration_days', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if not name or not slug or not price or not duration_days:
            messages.error(request, 'Name, slug, price, and duration are required.')
            return redirect('admin_panel:plan_create')

        try:
            price = float(price)
            duration_days = int(duration_days)
        except (ValueError, TypeError):
            messages.error(request, 'Invalid price or duration format.')
            return redirect('admin_panel:plan_create')

        if SubscriptionPlan.objects.filter(slug=slug).exists():
            messages.error(request, 'A plan with this slug already exists.')
            return redirect('admin_panel:plan_create')

        SubscriptionPlan.objects.create(
            name=name,
            slug=slug,
            description=description,
            price=price,
            duration_days=duration_days,
            is_active=is_active,
        )
        messages.success(request, f'Plan "{name}" has been created.')
        return redirect('admin_panel:plan_list')

    return render(request, 'admin_panel/subscriptions/plans/form.html', {
        'plan': None,
    })


@staff_required
def plan_edit(request, plan_id):
    from subscriptions.models import SubscriptionPlan

    plan = get_object_or_404(SubscriptionPlan, pk=plan_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        slug = request.POST.get('slug', '').strip()
        description = request.POST.get('description', '').strip()
        price = request.POST.get('price', '').strip()
        duration_days = request.POST.get('duration_days', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if not name or not slug or not price or not duration_days:
            messages.error(request, 'Name, slug, price, and duration are required.')
            return redirect('admin_panel:plan_edit', plan_id=plan.id)

        try:
            price = float(price)
            duration_days = int(duration_days)
        except (ValueError, TypeError):
            messages.error(request, 'Invalid price or duration format.')
            return redirect('admin_panel:plan_edit', plan_id=plan.id)

        if SubscriptionPlan.objects.filter(slug=slug).exclude(pk=plan.pk).exists():
            messages.error(request, 'A plan with this slug already exists.')
            return redirect('admin_panel:plan_edit', plan_id=plan.id)

        plan.name = name
        plan.slug = slug
        plan.description = description
        plan.price = price
        plan.duration_days = duration_days
        plan.is_active = is_active
        plan.save()
        messages.success(request, f'Plan "{name}" has been updated.')
        return redirect('admin_panel:plan_list')

    return render(request, 'admin_panel/subscriptions/plans/form.html', {
        'plan': plan,
    })
