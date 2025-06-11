import os

def consolidate_ts_files(root_dir, output_file):
    """
    Consolidates all .ts files in a directory and its subdirectories into a single output file.
    """
    with open(output_file, 'w', encoding='utf-8') as outfile:
        for subdir, _, files in os.walk(root_dir):
            for file in files:
                if file.endswith('.ts'):
                    filepath = os.path.join(subdir, file)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as infile:
                            outfile.write(f'// File: {filepath}\n')
                            outfile.write(infile.read())
                            outfile.write('\n\n') # Add a couple of newlines between files
                    except Exception as e:
                        print(f"Error reading file {filepath}: {e}")

if __name__ == "__main__":
    frontend_src_dir = 'c:\\GraphiX\\frontend\\src'
    output_filename = 'c:\\GraphiX\\consolidated_frontend_ts.txt'
    consolidate_ts_files(frontend_src_dir, output_filename)
    print(f"Consolidated all .ts files from {frontend_src_dir} into {output_filename}")