import os
import re

template_dir = r"c:\Users\ABHISHEK NANDA\Downloads\Kiosk\templates"

count = 0
for filename in os.listdir(template_dir):
    if filename.endswith(".html"):
        filepath = os.path.join(template_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        new_content = content
        
        # 1. Fix under-development.html title block
        if filename == "under-development.html":
            new_content = new_content.replace('<h1>{% block title %}', '<h1>{% block page_title %}')

        # 2. Fix '=""' expected 'endblock' in electricity-new-connection / gas-complaint
        # BS4 sometimes mangles empty attributes and outputs <some_tag ="" ...> which breaks if it contains Django tags.
        # Wait, the error is: Invalid block tag ... '=""', expected 'endblock'
        # This usually means something like `{% ="" %}` or `<div {% if %}="">` got mangled into something django thinks is a tag.
        # Let's just find `{% ="" %}` and remove it or `{%=""%}`
        # Actually BS4 doesn't do that, but let's blindly replace `{% ="" %}` if it exists, but wait, it says "Invalid block tag". This means it saw `{% ="" %}`. 
        new_content = re.sub(r'{%\s*=""\s*%}', '', new_content)

        # 3. Fix the orphaned `endfor` / `endif` after block content
        # We look for `{% block content %}` and everything up to `{% endif %}` that doesn't contain a real `<h1>` or something
        # Let's just remove `{% endfor %}` and `{% endif %}` and the `</div>` around them IF they appear right after `{% block content %}`
        
        # Match `{% block content %}` followed by at most 300 characters of anything (non-greedy) until `{% endif %}`
        # ONLY IF there is NO `{% for` or `{% if` in that matched span!
        
        def clean_garbage(match):
            inner = match.group(1)
            # If there's an opening for/if, we shouldn't strip the closing!
            if '{% for ' in inner or '{% if ' in inner:
                return match.group(0)
            return '{% block content %}'

        new_content = re.sub(r'{%\s*block content\s*%}([\s\S]{0,350}?{%\s*endif\s*%})', clean_garbage, new_content)
        
        # In case the block doesn't match because `{% endif %}` is missing or further, let's also just explicitly replace the specific orphaned string
        # using a simple string replace because it's identical across many files:
        broken_str = ' Messages \n            ">\n                    {{ message }}\n                </div>\n                {% endfor %}\n            </div>\n            {% endif %}'
        new_content = new_content.replace(broken_str, '')
        
        # Another variation:
        broken_str2 = '">\n                    {{ message }}\n                </div>\n                {% endfor %}\n            </div>\n            {% endif %}'
        new_content = new_content.replace(broken_str2, '')

        # Fallback for just the orphaned tags:
        # Match from `{% block content %}` to `{% endfor %}` with no `{% for` inside
        def clean_garbage_for(match):
            inner = match.group(1)
            if '{% for ' in inner: return match.group(0)
            return '{% block content %}'
            
        new_content = re.sub(r'{%\s*block content\s*%}([\s\S]{0,300}?{%\s*endfor\s*%})', clean_garbage_for, new_content)
        
        if new_content != content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            count += 1

print(f"Fixed {count} files.")
