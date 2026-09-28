from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.models.company import Company, User
from app.models.enums import UserRole
from app.schemas.auth import Token, UserLogin, UserOut, UserRegister
from app.services.auth_service import create_access_token, hash_password, verify_password
from app.services.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    company = db.query(Company).filter(Company.name == payload.company_name).first()
    is_first_user_in_company = company is None
    if company is None:
        company = Company(name=payload.company_name)
        db.add(company); db.flush()
    user = User(company_id=company.id, email=payload.email, hashed_password=hash_password(payload.password),
                full_name=payload.full_name, role=UserRole.ADMIN if is_first_user_in_company else UserRole.MANAGER)
    db.add(user); db.commit(); db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is disabled")
    access_token = create_access_token(subject=str(user.id), extra_claims={"company_id": str(user.company_id), "role": user.role.value})
    return Token(access_token=access_token)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/token", response_model=Token)
def login_form(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Same as /auth/login but accepts form data (username = email). This is what
    makes the 'Authorize' button in Swagger UI (/docs) work."""
    user = db.query(User).filter(User.email == form_data.username).first()
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is disabled")
    access_token = create_access_token(subject=str(user.id), extra_claims={"company_id": str(user.company_id), "role": user.role.value})
    return Token(access_token=access_token)