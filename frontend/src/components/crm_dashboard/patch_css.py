import os

filepath = r'c:\Users\reshm\OneDrive\Desktop\solvetaxx\solvetax_frontend\app\src\components\crm_dashboard\crm_dashboard.css'

with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    # Fix the drawer panel
    if 'display: grid;' in line and '409' in str(lines.index(line)+1): # heuristic
        new_lines.append(line.replace('display: grid;', 'display: flex; flex-direction: column;'))
    elif 'grid-template-rows: auto 1fr auto;' in line:
        continue # remove
    elif 'grid-template-columns: 100%;' in line:
        continue # remove
    # Fix the drawer body
    elif 'grid-row: 2;' in line:
        new_lines.append(line.replace('grid-row: 2;', 'flex: 1;'))
    elif 'display: block;' in line and '.drawer-body' in lines[lines.index(line)-2]: # heuristic
        new_lines.append(line.replace('display: block;', 'display: flex; flex-direction: column; gap: 24px;'))
    # Clean up grid assignments
    elif '.drawer-header { grid-row: 1; z-index: 10; }' in line:
        new_lines.append('.drawer-header { z-index: 10; }\n')
    elif '.drawer-footer { grid-row: 3; z-index: 10; }' in line:
        new_lines.append('.drawer-footer { z-index: 10; flex-shrink: 0; }\n')
    else:
        new_lines.append(line)

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Successfully patched crm_dashboard.css")
