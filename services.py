from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from repositories import (
    AdmissionRepository,
    FeeRepository,
    InstitutionRepository,
    ProgramRepository,
    RecommendationRepository,
    VerificationRepository,
)

VerificationStatus = Literal["unverified", "pending", "verified", "rejected", "outdated"]
VERIFICATION_STATUSES = {"unverified", "pending", "verified", "rejected", "outdated"}


class InstitutionService:
    def __init__(self, session: Session):
        self.repository = InstitutionRepository(session)

    def search(self, **filters):
        return self.repository.search(**filters)

    def count(self, **filters) -> int:
        return self.repository.count(**filters)

    def profile(self, institution_id: int):
        return self.repository.get_profile(institution_id)

    def compare(self, institution_ids: list[int]):
        return self.repository.compare(institution_ids)


class ProgramService:
    def __init__(self, session: Session):
        self.repository = ProgramRepository(session)

    def search(self, **filters):
        return self.repository.search(**filters)

    def count(self, **filters) -> int:
        return self.repository.count(**filters)


class AdmissionService:
    def __init__(self, session: Session):
        self.repository = AdmissionRepository(session)

    def records(self, institution_id: int):
        return self.repository.for_institution(institution_id)


class FeeService:
    def __init__(self, session: Session):
        self.repository = FeeRepository(session)

    def structures(self, institution_id: int):
        return self.repository.for_institution(institution_id)


class RecommendationService:
    def __init__(self, session: Session):
        self.repository = RecommendationRepository(session)

    def candidates(self, **filters):
        return self.repository.candidates(**filters)


class VerificationService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = VerificationRepository(session)

    def history(self, provenance_id: int):
        return self.repository.history(provenance_id)

    def record_review(
        self,
        provenance_id: int,
        status: VerificationStatus,
        *,
        reviewer: str | None = None,
        notes: str | None = None,
        verified_at: datetime | None = None,
    ):
        from models import VerificationRecord

        if status not in VERIFICATION_STATUSES:
            raise ValueError("Unsupported verification status.")
        provenance = self.repository.get_provenance(provenance_id)
        if provenance is None:
            raise LookupError("Provenance record not found.")
        if status == "verified" and (
            provenance.source_id is None or verified_at is None
        ):
            raise ValueError("Verified data requires a source and verification timestamp.")

        provenance.verification_status = status
        provenance.reviewer = reviewer
        provenance.verification_date = verified_at if status == "verified" else None
        record = VerificationRecord(
            provenance=provenance,
            source_id=provenance.source_id,
            verification_status=status,
            reviewer=reviewer,
            verified_at=provenance.verification_date,
            notes=notes,
        )
        self.session.add(record)
        self.session.flush()
        return record
