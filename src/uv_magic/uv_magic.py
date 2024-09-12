# uv_magic.py

import os
import subprocess
import tempfile
import json
import base64
import traceback
import shlex
import textwrap
import ast
from IPython.core.magic import Magics, magics_class, line_cell_magic
from IPython.display import display, HTML

@magics_class
class UVMagic(Magics):

    @line_cell_magic
    def uv_run(self, line, cell=None):
        """Run a cell with uv, using inline scripting and capturing output."""
        args = self.parse_arguments(line)
        python_spec = args.get('python_spec')  # For requires-python in script
        python_version = args.get('--python')  # For --python argument to uv
        dependencies = args.get('--with', [])
        use_matplotlib = 'matplotlib' in dependencies

        # Prepare the script with inline metadata and output capture
        script_content = self.build_script(cell, python_spec, dependencies, use_matplotlib)

        output_json = self.execute_script(script_content, python_version)
        self.process_output(output_json)

    def parse_arguments(self, line):
        """Parse the magic command arguments."""
        args = {}
        parts = shlex.split(line)
        i = 0
        while i < len(parts):
            part = parts[i]
            if part.startswith('python='):
                python_spec = part.split('=', 1)[1]
                # Ensure the python_spec includes an operator
                if not python_spec.startswith(('==', '>=', '<=', '>', '<', '~=', '!=')):
                    python_spec = f"=={python_spec}"
                args['python_spec'] = python_spec
                i += 1
            elif part == '--python' and i + 1 < len(parts):
                i += 1
                args['--python'] = parts[i]
                i += 1
            elif part == '--with' and i + 1 < len(parts):
                i += 1
                # Collect all dependencies until next option or end of line
                deps = []
                while i < len(parts) and not parts[i].startswith('--'):
                    deps.append(parts[i])
                    i += 1
                args['--with'] = deps
            else:
                i += 1
        return args

    def build_script(self, cell, python_spec, dependencies, use_matplotlib):
        """Construct the script content to be executed with uv."""
        # Prepare the script header, ensuring every line starts with '#'
        script_header_lines = ["# /// script"]
        if python_spec:
            requires_python_line = f"# requires-python = \"{python_spec}\""
            script_header_lines.append(requires_python_line)
        script_header_lines.append(f"# dependencies = {json.dumps(dependencies)}")
        script_header_lines.append("# ///")
        script_header = "\n".join(script_header_lines)

        # Replace 'print(' with 'custom_print(' in the user's code using AST
        cell_code = self.replace_print_statements(cell)

        # Indent user's code by 4 spaces to be inside the try block
        cell_code_indented = textwrap.indent(cell_code, '    ')

        # Prepare the script body without leading indentation
        script_body = textwrap.dedent("""\
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
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

{cell_code_indented}

    if {use_matplotlib}:
        for i in plt.get_fignums():
            fig = plt.figure(i)
            buf = BytesIO()
            fig.savefig(buf, format='png')
            buf.seek(0)
            img_str = base64.b64encode(buf.getvalue()).decode('utf-8')
            print(f'<div class="output-plot"><img src="data:image/png;base64,{{img_str}}\"></div>')
        plt.close('all')

except Exception as e:
    print(f'<pre style="color:red;">An error occurred: {{str(e)}}')
    print("Traceback:")
    traceback.print_exc()
    print('</pre>')

sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

result = {{"stdout": output_capture.getvalue(), "stderr": error_capture.getvalue()}}
print(json.dumps(result))
""").format(use_matplotlib=use_matplotlib, cell_code_indented=cell_code_indented)

        script_content = script_header + "\n" + script_body

        return script_content

    def replace_print_statements(self, code):
        """Replace print statements with custom_print to format outputs."""
        class PrintTransformer(ast.NodeTransformer):
            def visit_Call(self, node):
                if isinstance(node.func, ast.Name) and node.func.id == 'print':
                    node.func.id = 'custom_print'
                return self.generic_visit(node)

        tree = ast.parse(code)
        tree = PrintTransformer().visit(tree)
        ast.fix_missing_locations(tree)
        new_code = ast.unparse(tree)
        return new_code

    def execute_script(self, script_content, python_version):
        """Execute the script using uv and capture the output."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            os.chmod(temp_file.name, 0o600)  # Secure the temp file
            temp_file.write(script_content)
            temp_file_path = temp_file.name

        cmd = ['uv', 'run']
        if python_version:
            cmd.extend(['--python', python_version])
        cmd.append(temp_file_path)

        try:
            env = os.environ.copy()
            env.pop('MPLBACKEND', None)  # Remove any existing MPLBACKEND setting
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
            return result.stdout
        except subprocess.CalledProcessError as e:
            error_message = e.stderr or e.stdout
            display(HTML(f"<pre style='color:red;'>Error running uv:\n{error_message}</pre>"))
            return None
        finally:
            os.unlink(temp_file_path)

    def process_output(self, output_json):
        """Process and display the output from the executed script."""
        if not output_json:
            return

        try:
            output = json.loads(output_json)
            stdout = output.get('stdout', '')
            stderr = output.get('stderr', '')

            display(HTML(f"""
            <style>
            .output-text {{ white-space: pre-wrap; }}
            .output-plot {{ text-align: center; }}
            </style>
            {stdout}
            """))
            if stderr:
                print("\nSTDERR:")
                print(stderr)
        except json.JSONDecodeError:
            print("Failed to decode JSON. Raw output:")
            print(output_json)

def load_ipython_extension(ipython):
    """Load the uv_magic extension in IPython."""
    ipython.register_magics(UVMagic)
