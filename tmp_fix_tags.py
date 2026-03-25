import os
import re

template_dir = r"c:\Users\ABHISHEK NANDA\Downloads\Kiosk\templates"

# The garbage is usually at the start of {% block content %}.
# It looks like orphaned tags. We will use a regex to clean up the specific mangled message block.

mangled_pattern = re.compile(
    r'{%\s*block content\s*%}\s*'
    r'(?:<!--\s*Messages\s*-->\s*)?'
    r'(?:Messages\s*)?'
    r'(?:">\s*{{ message }}\s*</div>\s*)?'
    r'{%\s*endfor\s*%}\s*'
    r'(?:</div>\s*)?'
    r'{%\s*endif\s*%}', 
    re.IGNORECASE | re.DOTALL
)

count = 0
for filename in os.listdir(template_dir):
    if filename.endswith(".html"):
        filepath = os.path.join(template_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Fix the title block duplication in under-development
        if filename == "under-development.html":
            content = content.replace('<h1>{% block title %}', '<h1>{% block page_title %}')
            
        # Check if it has orphaned {% endfor %} without a {% for %} BEFORE IT in the block content
        # An easier way: just remove the exact mangled message string block
        new_content = mangled_pattern.sub('{% block content %}', content)
        
        # If the mangled block has variations, let's also do a fallback regex to strip leading endfors
        # Sometimes it's just `{% endfor %} \n </div> \n {% endif %}` inside `{% block content %}` 
        fallback_pattern = re.compile(
            r'({%\s*block content\s*%}\s*(?:<[^>]+>\s*)*[^<%]*?)' # match the start of block content and some tags/text
            r'{%\s*endfor\s*%}\s*(?:</[^>]+>\s*)*'
            r'{%\s*endif\s*%}',
            re.IGNORECASE | re.DOTALL
        )
        
        # Let's write a more robust cleaner for the start of block content.
        # It's better to just manually match the exact garbage I saw in auth.html:
        garbage_re = re.compile(r'{%\s*block content\s*%}[\s\S]{0,150}?{%\s*endfor\s*%}[\s\S]{0,50}?{%\s*endif\s*%}')
        # We will replace all that with `{% block content %}`
        match = garbage_re.search(new_content)
        if match:
            # check if there's a '{% for ' inside the matched text
            if '{% for ' not in match.group():
                new_content = garbage_re.sub('{% block content %}', new_content)

        if filename == "electricity-new-connection.html" or filename == "gas-complaint.html":
            # "Invalid block tag on line 352: '=""', expected 'endblock'."
            # This is caused by BeautifulSoup mangling an attribute. Let's fix it after.
            pass
            
        if new_content != content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            count += 1

print(f"Fixed mangled tags in {count} templates.")
