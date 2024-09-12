import os
import subprocess
import tempfile
import textwrap
from IPython.core.magic import (Magics, magics_class, line_cell_magic)
from IPython.display import display, HTML
import json
import traceback
import base64


@magics_class
class UVMagic(Magics):

    @line_cell_magic
    def uv_run(self, line, cell=None):
        """Run a cell with uv, using inline scripting and capturing output."""
        parts = line.split()
        python_version = ">=3.7"  # default
        dependencies = []
        
        for i, part in enumerate(parts):
            if part.startswith("python="):
                python_version = part.split("=", 1)[1]
                if not python_version.startswith(("=", "<", ">", "~", "^")):
                    python_version = "=" + python_version
            elif part == "--with" and i+1 < len(parts):
                dependencies = parts[i+1:]
                break
        
        use_matplotlib = 'matplotlib' in dependencies
        
        # Prepare the script with inline metadata and output capture
        script_content = f"""# /// script
# requires-python = "{python_version}"
# dependencies = {json.dumps(dependencies)}
# ///

import sys
from io import StringIO, BytesIO
import json
import traceback
import base64

class OutputCapture:
    def __init__(self):
        self.outputs = []

    def write(self, s):
        self.outputs.append(s)

    def flush(self):
        pass

    def getvalue(self):
        return ''.join(self.outputs)

output_capture = OutputCapture()
error_capture = OutputCapture()

sys.stdout = output_capture
sys.stderr = error_capture

def custom_print(*args, **kwargs):
    print('<div class="output-text">', end='')
    print(*args, **kwargs)
    print('</div>', end='')

try:
    if {use_matplotlib}:
        custom_print("Setting matplotlib backend to 'Agg'...")
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        custom_print("matplotlib imported successfully.")
        custom_print("matplotlib version:", matplotlib.__version__)
        custom_print("matplotlib backend:", matplotlib.get_backend())
    
    {textwrap.indent(cell.replace('print(', 'custom_print('), '    ')}

    if {use_matplotlib}:
        custom_print("Capturing matplotlib figures...")
        for i in plt.get_fignums():
            fig = plt.figure(i)
            buf = BytesIO()
            fig.savefig(buf, format='png')
            buf.seek(0)
            img_str = base64.b64encode(buf.getvalue()).decode('utf-8')
            print(f'<div class="output-plot"><img src="data:image/png;base64,{{img_str}}"></div>')
        custom_print(f"Number of figures: {{len(plt.get_fignums())}}")
        plt.close('all')

except Exception as e:
    custom_print(f"An error occurred: {{str(e)}}")
    custom_print("Traceback:")
    traceback.print_exc(file=sys.stdout)

sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

result = {{"stdout": output_capture.getvalue(), "stderr": error_capture.getvalue()}}
print(json.dumps(result))
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            temp_file.write(script_content)
            temp_file_path = temp_file.name
        
        cmd = ['uv', 'run', temp_file_path]
        
        try:
            env = os.environ.copy()
            env.pop('MPLBACKEND', None)  # Remove any existing MPLBACKEND setting
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
            
            try:
                output = json.loads(result.stdout)
                display(HTML(f"""
                <style>
                .output-text {{ white-space: pre-wrap; }}
                .output-plot {{ text-align: center; }}
                </style>
                {output['stdout']}
                """))
                if output['stderr']:
                    print("\nSTDERR:")
                    print(output['stderr'])
            except json.JSONDecodeError:
                print("Failed to decode JSON. Raw output:")
                print(result.stdout)
                print("Error output:")
                print(result.stderr)
        except subprocess.CalledProcessError as e:
            print(f"Error running uv: {e}")
            print("STDOUT:")
            print(e.stdout)
            print("STDERR:")
            print(e.stderr)
        finally:
            os.unlink(temp_file_path)

# Load the magic
def load_ipython_extension(ipython):
    ipython.register_magics(UVMagic)

    