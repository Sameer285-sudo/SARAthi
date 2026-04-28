"""Seed one user per role. Run once: python -m auth_service.seed"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uuid
from shared.db import Base, SessionLocal, engine
from shared.models import User
from shared.auth.password import hash_password

Base.metadata.create_all(bind=engine)

SEED_USERS = [
    {
        "user_id":    str(uuid.uuid4()),
        "username":   "state_admin",
        "email":      "state.admin@pds360.gov.in",
        "password":   "Admin@1234",
        "full_name":  "Ravi Kumar (State Admin)",
        "role":       "STATE_ADMIN",
        "state_id":   "AP",
    },
    {
        "user_id":    str(uuid.uuid4()),
        "username":   "dist_admin",
        "email":      "dist.admin@pds360.gov.in",
        "password":   "Admin@1234",
        "full_name":  "Lakshmi Devi (District Admin)",
        "role":       "DISTRICT_ADMIN",
        "state_id":   "AP",
        "district_id": "Guntur",
    },
    {
        "user_id":    str(uuid.uuid4()),
        "username":   "mandal_admin",
        "email":      "mandal.admin@pds360.gov.in",
        "password":   "Admin@1234",
        "full_name":  "Suresh Rao (Mandal Admin)",
        "role":       "MANDAL_ADMIN",
        "state_id":   "AP",
        "district_id": "Guntur",
        "mandal_id":  "Rajupalem",
    },
    {
        "user_id":    str(uuid.uuid4()),
        "username":   "afso_user",
        "email":      "afso@pds360.gov.in",
        "password":   "Admin@1234",
        "full_name":  "Priya Sharma (AFSO)",
        "role":       "AFSO",
        "state_id":   "AP",
        "district_id": "Guntur",
        "mandal_id":  "Rajupalem",
    },
    {
        "user_id":    str(uuid.uuid4()),
        "username":   "fps_dealer",
        "email":      "fps.dealer@pds360.gov.in",
        "password":   "Dealer@1234",
        "full_name":  "Venkat Reddy (FPS Dealer)",
        "role":       "FPS_DEALER",
        "state_id":   "AP",
        "district_id": "Guntur",
        "mandal_id":  "Rajupalem",
        "fps_id":     "FPS-001",
    },
    {
        "user_id":    str(uuid.uuid4()),
        "username":   "beneficiary",
        "email":      "beneficiary@pds360.gov.in",
        "password":   "User@1234",
        "full_name":  "Anitha Kumari (Beneficiary)",
        "role":       "RATION_CARD_HOLDER",
        "state_id":   "AP",
        "district_id": "Guntur",
        "mandal_id":  "Rajupalem",
        "fps_id":     "FPS-001",
    },
]


def seed():
    db = SessionLocal()
    try:
        created = 0
        for u in SEED_USERS:
            if db.query(User).filter(User.username == u["username"]).first():
                print(f"  skip {u['username']} (already exists)")
                continue
            db.add(User(
                user_id=u["user_id"],
                username=u["username"],
                email=u["email"],
                hashed_password=hash_password(u["password"]),
                full_name=u["full_name"],
                role=u["role"],
                state_id=u.get("state_id"),
                district_id=u.get("district_id"),
                mandal_id=u.get("mandal_id"),
                fps_id=u.get("fps_id"),
            ))
            created += 1
            print(f"  created {u['username']} ({u['role']})")
        db.commit()
        print(f"\nDone — {created} user(s) created.")
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    if "--reset" in sys.argv:
        db = SessionLocal()
        try:
            usernames = [u["username"] for u in SEED_USERS]
            deleted = db.query(User).filter(User.username.in_(usernames)).delete(synchronize_session=False)
            db.commit()
            print(f"  Deleted {deleted} existing seed user(s).")
        finally:
            db.close()
    seed()
