import uuid as uuidlib

from django.db import models


class BaseModel(models.Model):
    uuid = models.UUIDField(default=uuidlib.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Tenant(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        SUSPENDED = "SUSPENDED"
        CANCELLED = "CANCELLED"

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    country = models.CharField(max_length=64, default="YE")
    currency = models.CharField(max_length=8, default="YER")
    timezone = models.CharField(max_length=64, default="Asia/Aden")
    default_language = models.CharField(max_length=8, default="ar")

    class Meta:
        indexes = [models.Index(fields=["status"])]


class Branch(BaseModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="branches")
    name = models.CharField(max_length=200)
    is_main = models.BooleanField(default=False)


class Warehouse(BaseModel):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="warehouses")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
