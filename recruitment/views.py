from django.shortcuts import render
from recruitment.models import CandidateResult
# Create your views here.
def dashboard(request):

    candidates = CandidateResult.objects.all()

    total = candidates.count()

    highly = candidates.filter(
        decision="Highly Recommended"
    ).count()

    recommended = candidates.filter(
        decision="Recommended"
    ).count()

    consider = candidates.filter(
        decision="Consider"
    ).count()

    not_recommended = candidates.filter(
        decision="Not Recommended"
    ).count()

    context = {

        "total": total,

        "highly": highly,

        "recommended": recommended,

        "consider": consider,

        "not_recommended": not_recommended,

        "candidates": candidates.order_by(
            "-final_score"
        )
    }

    return render(
        request,
        "dashboard.html",
        context
    )