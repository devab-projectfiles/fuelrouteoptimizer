from django.urls import path

from .views import RouteOptimizationView

urlpatterns = [
    path(
        "route/",
        RouteOptimizationView.as_view(),
        name="route-optimization",
    ),
]
