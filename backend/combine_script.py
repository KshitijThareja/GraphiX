import os

# The directory containing the python files to combine
source_dir = r'c:\GraphiX\backend\app'

# The name of the output file
output_file = r'c:\GraphiX\backend\combined_app.py'

# Get a list of all .py files in the source directory and its subdirectories
files_to_combine = []
try:
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith('.py'):
                files_to_combine.append(os.path.join(root, file))
    files_to_combine.sort()
except FileNotFoundError:
    print(f"Error: Source directory not found at '{source_dir}'")
    exit()


# Combine the files
with open(output_file, 'w', encoding='utf-8') as outfile:
    for filepath in files_to_combine:
        # Get the relative path for the header to be more informative
        relative_path = os.path.relpath(filepath, source_dir)
        outfile.write(f'# {'='*30}\\n')
        outfile.write(f'# Filename: {relative_path}\\n')
        outfile.write(f'# {'='*30}\\n\\n')
        try:
            with open(filepath, 'r', encoding='utf-8') as infile:
                outfile.write(infile.read())
            outfile.write('\\n\\n')
        except Exception as e:
            outfile.write(f"# ERROR READING FILE: {relative_path}\\n")
            outfile.write(f"# {e}\\n\\n")

print(f"Successfully combined {len(files_to_combine)} python files into '{output_file}'")