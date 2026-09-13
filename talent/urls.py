from .views import home
from django.urls import path
from .views import (
    job_list,
    job_detail,
    apply_job,
    candidate_ranking,
    ranking_jobs,
    ranking_by_job,
    candidate_detail,
    create_job,
    test_semantic_matching,
    my_applications
)


urlpatterns = [

     path(
        "",
        home,
        name="home"
    ),

    path(
        'jobs/',
        job_list,
        name='job_list'
    ),

    path(
        'jobs/<int:job_id>/',
        job_detail,
        name='job_detail'
    ),

    path(
        'jobs/<int:job_id>/apply/',
        apply_job,
        name='apply_job'
    ),
    path(
        'ranking/',
        candidate_ranking,
        name='candidate_ranking'
    ),

    path(
        'ranking-jobs/',
        ranking_jobs,
        name='ranking_jobs'
    ),

    path(
        'ranking-jobs/<int:job_id>/',
        ranking_by_job,
        name='ranking_by_job'
    ),

    path(
        'test-semantic/',
        test_semantic_matching,
        name='test_semantic'
    ),

    path(
        "ranking/<int:application_id>/",
        candidate_detail,
        name="candidate_detail"
    ),
    path(

        "jobs/create/",

        create_job,

        name="create_job"

    ),

    path(
        "my-applications/",
        my_applications,
        name="my_applications"
    ),

]