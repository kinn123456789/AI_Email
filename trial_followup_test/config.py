from dotenv import load_dotenv
from supabase import create_client
import os

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

# Existing batch to use for test enrollments
DEFAULT_BATCH_ID = "11517685-ae9e-4609-a494-331f7704812e"
DEFAULT_BATCH_VERSION = 1

# Password used for all generated auth users
DEFAULT_PASSWORD = "Test12345!"

# Email prefix for generated test parents
EMAIL_PREFIX = "trialtest"

# Name prefix so cleanup can identify test data
TEST_PREFIX = "TFTEST"

# Number of scenarios to create
DEFAULT_SCENARIOS = 5