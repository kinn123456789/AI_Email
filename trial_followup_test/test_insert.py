import uuid
from helpers import (
    create_auth_user,
    insert_user,
    insert_parent,
    insert_learner,
    insert_enrollment,
    insert_free_trial,
    generate_test_email,
    generate_parent_name,
    generate_learner_name,
)

print("Creating Parent Auth User...")

parent_email = f"support+{uuid.uuid4().hex[:8]}@coralacademy.com"

parent_auth = create_auth_user(parent_email)

parent_id = parent_auth.id

print("Parent ID:", parent_id)

print("Creating Parent User...")


parent_name = generate_parent_name(1)
learner_name = generate_learner_name(1)

insert_user(
    user_id=parent_id,
    name=parent_name,
    user_type=["parent"]
)

print("Creating Parent Record...")

insert_parent(parent_id)

print("Creating Learner Auth User...")

learner_email = f"{parent_id}@learner.coralacademy.com"

learner_auth = create_auth_user(learner_email)

learner_id = learner_auth.id

print("Learner ID:", learner_id)

print("Creating Learner User...")

insert_user(
    user_id=learner_id,
    name=learner_name,
    user_type=["learner"]
)

print("Creating Learner Record...")

insert_learner(
    learner_id=learner_id,
    parent_id=parent_id,
    learner_name=learner_name
)

print("Creating Enrollment...")

enrollment_id = insert_enrollment(
    learner_id
)

print(enrollment_id)

print("Creating Trial Pass...")

trial_id = insert_free_trial(
    parent_id,
    enrollment_id
)

print(trial_id)

print("\n✅ SUCCESS")
print("Parent Name :", parent_name)
print("Learner Name:", learner_name)
print("Parent Email:", parent_email)
print("Parent ID   :", parent_id)
print("Learner ID  :", learner_id)