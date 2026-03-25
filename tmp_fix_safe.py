import os

path = r"c:\Users\ABHISHEK NANDA\Downloads\Kiosk\display\views.py"
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
indent_to_match = ""

for line in lines:
    if "Fallback to sample data" in line:
        skip = True
        indent = len(line) - len(line.lstrip())
        indent_to_match = " " * (indent - 4)
        
        # Insert the error message with the exact same indentation as the comment
        new_lines.append(" " * indent + "messages.error(request, 'Record not found. Please verify your details.')\n")
        new_lines.append(" " * indent + "context['show_results'] = False\n")
        # Empty the bills/data lists just in case
        new_lines.append(" " * indent + "bills = []\n")
        new_lines.append(" " * indent + "data = []\n")
        continue

    if skip:
        curr_indent = len(line) - len(line.lstrip())
        if line.strip() and curr_indent <= len(indent_to_match):
            skip = False
            new_lines.append(line)
        continue
        
    new_lines.append(line)

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Successfully processed {len(lines)} lines")
