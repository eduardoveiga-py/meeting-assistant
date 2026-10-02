import os


def replace_in_file(filepath, old_texts, new_text):
    with open(filepath, encoding='utf-8') as f:
        content = f.read()
    
    modified = content
    for old in old_texts:
        modified = modified.replace(old, new_text)
        
    if content != modified:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(modified)
        print(f"Updated {filepath}")

replace_in_file('.github/workflows/release.yml', ['0.6.0rc1'], '0.7.0')
replace_in_file('.github/workflows/release.yml', ['0.6.0-rc1'], '0.7.0')
replace_in_file('.github/workflows/release.yml', ['--prerelease '], '')

replace_in_file('README.md', ['0.6.0-dev1', '0.6.0-rc1'], '0.7.0')
replace_in_file('packaging/MeetingAssistant.iss', ['0.6.0-dev1', '0.6.0-rc1'], '0.7.0')
replace_in_file('packaging/README.md', ['0.6.0-dev1', '0.6.0-rc1'], '0.7.0')
replace_in_file('pyproject.toml', ['0.6.0rc1', '0.6.0-rc1'], '0.7.0')
replace_in_file('src/meeting_assistant/__init__.py', ['0.6.0rc1', '0.6.0-rc1'], '0.7.0')

if os.path.exists('docs/releases/v0.6.0-rc1.md'):
    os.rename('docs/releases/v0.6.0-rc1.md', 'docs/releases/v0.7.0.md')
replace_in_file('docs/releases/v0.7.0.md', ['0.6.0-rc1', '0.6.0-dev1'], '0.7.0')
replace_in_file('docs/releases/v0.7.0.md', ['-rc1'], '')

print("Done")
