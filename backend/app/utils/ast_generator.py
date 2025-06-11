# c:\GraphiX\backend\app\utils\ast_generator.py
import os
import logging
from typing import Dict, Any, Optional

from tree_sitter import Language, Parser
# We are bypassing tree_sitter_languages.get_language due to the TypeError

logger = logging.getLogger(__name__)

# --- Start of Tree-sitter Python grammar loading ---
PYTHON_LANGUAGE: Optional[Language] = None

try:
    # Import the pre-compiled tree-sitter-python language package
    import tree_sitter_python as tspython
    PYTHON_LANGUAGE = Language(tspython.language())
    logger.info("Successfully loaded Tree-sitter Python grammar using pre-compiled package.")
except ImportError:
    logger.error(
        "'tree-sitter-python' package not found. Please install it: pip install tree-sitter-python. "
        "Tree-sitter based Python AST parsing will be unavailable."
    )
    PYTHON_LANGUAGE = None
except Exception as e:
    logger.error(
        f"Failed to load Tree-sitter Python grammar from pre-compiled package: {e}. "
        "Tree-sitter based Python AST parsing will be unavailable."
    )
    PYTHON_LANGUAGE = None # Ensure it's None on failure
# --- End of Tree-sitter Python grammar loading ---


class ASTGenerator:
    def __init__(self):
        self.python_parser: Optional[Parser] = None
        if PYTHON_LANGUAGE:
            self.python_parser = Parser(PYTHON_LANGUAGE) # Pass language to constructor
            logger.info("Python parser initialized successfully with Tree-sitter.")
        else:
            logger.error(
                "Python parser (Tree-sitter) not initialized due to grammar loading/building failure. "
                "LLM documentation features requiring detailed AST parsing might be affected."
            )

        # Placeholder for other language parsers if needed in the future
        # self.javascript_parser: Optional[Parser] = None
        # ... setup for other languages ...

    def get_language_parser(self, language: str) -> Optional[Parser]:
        """Returns the Tree-sitter parser for the specified language."""
        language_lower = language.lower()
        if language_lower == 'python':
            if not self.python_parser:
                logger.warning("Python parser requested but not available (Tree-sitter).")
            return self.python_parser
        # Example for JavaScript:
        # elif language_lower == 'javascript':
        #     return self.javascript_parser
        
        logger.warning(f"No Tree-sitter parser available or configured for language: {language}")
        return None

    def parse_file_content(self, file_content_bytes: bytes, language: str) -> Optional[Any]: # Tree-sitter AST node is Any
        """
        Parses the given file content bytes using the appropriate Tree-sitter parser.
        Returns the Tree-sitter AST root node, or None if parsing fails or parser is unavailable.
        """
        parser = self.get_language_parser(language)
        if not parser:
            logger.error(f"Cannot parse content: No Tree-sitter parser available for language '{language}'.")
            return None
        
        try:
            tree = parser.parse(file_content_bytes)
            return tree.root_node
        except Exception as e:
            logger.error(f"Error parsing content with Tree-sitter for language '{language}': {e}")
            return None

    def parse_file(self, file_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Reads a file and parses its content using Tree-sitter.
        Determines language from file extension if not provided.
        Returns a dictionary with 'ast' (Tree-sitter root node), 'content' (str), and 'error' (str/None).
        """
        lang_to_use = language
        if not lang_to_use:
            _, ext = os.path.splitext(file_path)
            if ext == '.py':
                lang_to_use = 'python'
            # elif ext == '.js': lang_to_use = 'javascript' # Example for JS
            else:
                msg = f"Could not determine language for file {file_path} from extension '{ext}'."
                logger.warning(msg)
                return {"ast": None, "content": "", "error": msg}
        
        logger.debug(f"Parsing file {file_path} with language {lang_to_use} using Tree-sitter.")

        try:
            with open(file_path, 'rb') as f:
                file_content_bytes = f.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return {"ast": None, "content": "", "error": str(e)}

        try:
            file_content_str = file_content_bytes.decode('utf-8')
        except UnicodeDecodeError:
            logger.warning(f"Could not decode file {file_path} as UTF-8. Using replacement characters.")
            file_content_str = file_content_bytes.decode('utf-8', errors='replace')
            
        parser = self.get_language_parser(lang_to_use)
        if not parser:
            err_msg = f"No Tree-sitter parser for '{lang_to_use}' for {file_path}."
            logger.error(err_msg)
            return {"ast": None, "content": file_content_str, "error": err_msg}

        try:
            tree = parser.parse(file_content_bytes)
            logger.debug(f"Successfully parsed {file_path} with Tree-sitter.")
            return {"ast": tree.root_node, "content": file_content_str, "error": None}
        except Exception as e:
            err_msg = f"Error during Tree-sitter parsing of {file_path}: {e}"
            logger.error(err_msg)
            return {"ast": None, "content": file_content_str, "error": err_msg}

    def _execute_ts_query(self, node_to_search_in, query_string: str):
        """Helper to execute a Tree-sitter query, assuming Python language."""
        if not PYTHON_LANGUAGE:
            logger.error("Tree-sitter Python language not loaded. Cannot execute query.")
            return []
        try:
            query = PYTHON_LANGUAGE.query(query_string)
            captures = query.captures(node_to_search_in)
            return captures
        except Exception as e:
            logger.error(f"Error executing Tree-sitter query: {e}")
            return []

    def find_node_and_get_source(
        self,
        ast_root_node,
        node_identifier: str,
        target_node_type: str,
        source_code_bytes: bytes
    ) -> Optional[str]:
        """
        Finds a specific node (function, class, or method) in the Tree-sitter AST 
        and returns its source code.

        Args:
            ast_root_node: The root node of the Tree-sitter AST for the file.
            node_identifier: The name of the node to find. 
                             For functions/classes: "name". 
                             For methods: "ClassName.methodName".
            target_node_type: Type of the node ("function", "class", "method").
            source_code_bytes: The byte content of the source file.

        Returns:
            The source code of the found node as a string, or None if not found.
        """
        if not self.python_parser:
            logger.error("Python parser not available (Tree-sitter). Cannot find node.")
            return None
        if not ast_root_node:
            logger.error("AST root node is None. Cannot find node.")
            return None

        parts = node_identifier.split('.')
        found_node = None

        if target_node_type == "function":
            if len(parts) != 1:
                logger.error(f"Invalid identifier '{node_identifier}' for type 'function'. Expected single name.")
                return None
            name_to_find = parts[0]
            query_string = """
            (function_definition
              name: (identifier) @name) @definition
            """
            captures = self._execute_ts_query(ast_root_node, query_string)
            for captured_node, name_in_query in captures:
                if name_in_query == 'definition':
                    name_node = captured_node.child_by_field_name("name")
                    if name_node and name_node.text.decode('utf-8', errors='ignore') == name_to_find:
                        found_node = captured_node
                        break
        
        elif target_node_type == "class":
            if len(parts) != 1:
                logger.error(f"Invalid identifier '{node_identifier}' for type 'class'. Expected single name.")
                return None
            name_to_find = parts[0]
            query_string = """
            (class_definition
              name: (identifier) @name) @definition
            """
            captures = self._execute_ts_query(ast_root_node, query_string)
            for captured_node, name_in_query in captures:
                if name_in_query == 'definition':
                    name_node = captured_node.child_by_field_name("name")
                    if name_node and name_node.text.decode('utf-8', errors='ignore') == name_to_find:
                        found_node = captured_node
                        break

        elif target_node_type == "method":
            if len(parts) != 2:
                logger.error(f"Invalid identifier '{node_identifier}' for type 'method'. Expected 'ClassName.methodName'.")
                return None
            class_name_to_find, method_name_to_find = parts[0], parts[1]

            class_query_string = """
            (class_definition
              name: (identifier) @name) @definition
            """
            class_captures = self._execute_ts_query(ast_root_node, class_query_string)
            class_node_found = None
            for captured_node, name_in_query in class_captures:
                if name_in_query == 'definition':
                    name_node = captured_node.child_by_field_name("name")
                    if name_node and name_node.text.decode('utf-8', errors='ignore') == class_name_to_find:
                        class_node_found = captured_node
                        break
            
            if not class_node_found:
                logger.debug(f"Method search: Class '{class_name_to_find}' not found in AST for identifier '{node_identifier}'.")
                return None
            
            method_query_string = """
            (function_definition
              name: (identifier) @name) @definition
            """
            method_captures = self._execute_ts_query(class_node_found, method_query_string)
            for captured_node, name_in_query in method_captures:
                if name_in_query == 'definition':
                    name_node = captured_node.child_by_field_name("name")
                    if name_node and name_node.text.decode('utf-8', errors='ignore') == method_name_to_find:
                        found_node = captured_node
                        break
        else:
            logger.error(f"Unsupported target_node_type: '{target_node_type}' for identifier '{node_identifier}'.")
            return None

        if found_node:
            start = found_node.start_byte
            end = found_node.end_byte
            return source_code_bytes[start:end].decode('utf-8', errors='ignore')
        else:
            logger.debug(f"Node '{node_identifier}' of type '{target_node_type}' not found in AST.")
            return None


# Example usage (optional, for testing this module directly)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG) # Use DEBUG for more detailed output during test
    logger.info("Testing ASTGenerator standalone...")
    
    # This test part assumes tree-sitter-python source is in vendor/tree-sitter-python
    # For the test to fully pass, you need the actual grammar files there.
    # If they are missing, it will log an error but the script won't crash.
    
    ast_gen = ASTGenerator()
    if ast_gen.python_parser:
        logger.info("ASTGenerator initialized with Python parser.")
        
        dummy_py_file = os.path.join(os.path.dirname(__file__), 'dummy_test.py')
        with open(dummy_py_file, 'w') as f:
            f.write("def hello():\n  print('world')\n\nclass MyClass:\n  pass\n")
        
        logger.info(f"Attempting to parse: {dummy_py_file}")
        parse_result = ast_gen.parse_file(dummy_py_file)

        if parse_result["ast"]:
            logger.info(f"Successfully parsed dummy_test.py. AST root type: {parse_result['ast'].type}")
            # To see the structure: print(parse_result["ast"].sexp())
        else:
            logger.error(f"Failed to parse dummy_test.py: {parse_result['error']}")
        
        try:
            os.remove(dummy_py_file)
            logger.info(f"Cleaned up {dummy_py_file}")
        except OSError as e:
            logger.error(f"Error cleaning up {dummy_py_file}: {e}")
            
    else:
        logger.error("ASTGenerator could not initialize Python parser. Standalone test failed.")

    # Note: The compiled grammar (e.g., python_grammar.dll) will remain after this test.
    # This is generally fine. You only need to delete it if you want to force a rebuild.