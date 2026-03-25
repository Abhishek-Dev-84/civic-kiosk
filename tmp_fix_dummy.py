import os
import re

VIEWS_FILE = r"c:\Users\ABHISHEK NANDA\Downloads\Kiosk\display\views.py"

with open(VIEWS_FILE, 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern for checking consumer / fallback logic
# "else:\n    # Fallback to sample data\n... except"
# We'll use a regex to match the else block that generates bills, taxes, etc.
# Typically starts with "else:\n                    # Fallback to sample data"

# For Electricity, Water, Gas, etc.
# We will use regex to find:
# else:\s+# Fallback to sample data(.*?)except Exception as e:
# and replace it with:
# else:\n                    messages.error(request, 'Consumer/Record not found. Please verify your details.')\n                except Exception as e:

def replace_fallback(match):
    indent = match.group(1) # get the indentation of the else
    return f"{indent}else:\n{indent}    messages.error(request, 'Record not found. Please verify your details.')\n{indent}    context['show_results'] = False\n{indent}except Exception as e:"

# Match the 'else:' block followed by fallback comment up to the 'except' block.
# We need to capture the exact indentation of the else to keep the except aligned if necessary, 
# although except is aligned with try, not else.
new_content = re.sub(r'(\s+)else:\s+# Fallback to sample data.*?\1except Exception as e:', replace_fallback, content, flags=re.DOTALL)

# Handle cases that don't have exactly "Fallback to sample data" but generate random stuff
# E.g. in payment confirmations
# payment_id = f"TXN{random.randint(100000, 999999)}" -> should just stay as is IF it's a real creation fallback, 
# but if it's meant to be a real db operation, it shouldn't use random.
# Actually, random payment IDs for testing are fine if Razorpay is in TEST mode (which the previous chat said it should be! "Setting up Razorpay in TEST MODE for payments.")
# The prompt says: "Setups: Razorpay in TEST MODE for payments."
# If Razorpay isn't fully integrated, random TXN IDs are the ONLY way the app works without a real gateway.
# "Remove all dummy data generation... Replace any dummy logic with real logic" means we should either use real DB, OR real Razorpay.

with open(VIEWS_FILE, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Done replacing fallbacks")
