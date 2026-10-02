# --- Users ---------------------------------------------------------
if not User.objects.filter(username="admin28").exists():
    User.objects.create_superuser(
        username="admin28", email="admin28@example.com", password="Phase28Pass!"
    )

for uname in ["recruiter28", "hrmanager28"]:
    if not User.objects.filter(username=uname).exists():
        User.objects.create_user(
            username=uname,
            password="Phase28Pass!",
            # TASK F follow-up (2026-10-02): email is now unique and
            # the model's USERNAME_FIELD -- two users with email=""
            # would violate that constraint (hit for real: this
            # exact script seeded the two blank-email duplicates that
            # broke the accounts.0005 migration the first time it ran).
            email=f"{uname}@example.com",
            is_verified=True,
        )

print("Login for testing -> username: admin28 / password: Phase28Pass!")