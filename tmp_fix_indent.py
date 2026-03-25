import re

path = r"c:\Users\ABHISHEK NANDA\Downloads\Kiosk\display\views.py"
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# The bad block looks like:
# {indent}else:
# {indent}messages.error(request, 'Record not found. Please verify your details.')
# {indent}context['show_results'] = False
# {indent}except Exception as e:

def fixthem(match):
    indent = match.group(1) # e.g. 16 spaces
    # except should be text-indented 4 spaces LESS than else
    except_indent = indent[:-4] if len(indent) >= 4 else ""
    return (
        f"{indent}else:\n"
        f"{indent}    messages.error(request, 'Record not found. Please verify your details.')\n"
        f"{indent}    context['show_results'] = False\n"
        f"{except_indent}except Exception as e:"
    )

new_content = re.sub(
    r'([ \t]+)else:\n\1messages\.error\(request, \'Record not found\. Please verify your details\.\'\)\n\1context\[\'show_results\'\] = False\n\1except Exception as e:',
    fixthem,
    content
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Done fixing indents")
