import os
import ast
import logging
from typing import Dict, List, Set, Optional, Tuple, Any
import time
import shutil
import ast
import os
from .enhanced_callgraph import EnhancedCallgraphGenerator
from .dynamic_callgraph_builder import DynamicCallGraphBuilder
import tempfile
from .callgraph import rate_limited  # Added import
import traceback  # Import traceback for error handling


logger = logging.getLogger(__name__)


class ResearchCallgraphGenerator(EnhancedCallgraphGenerator):
    def __init__(self, framework: str = "generic", max_depth: int = 8):
        super().__init__()
        self.base_imports = getattr(self, 'base_imports', {})
        self.max_depth = max_depth
        self.dynamic_builder: Optional[DynamicCallGraphBuilder] = None
        self.initial_framework_hint = framework

    def _get_python_files(self, repo_path: str) -> List[str]:
        """Helper function to get all Python files in the repository."""
        python_files = []
        for root, dirs, files in os.walk(repo_path):
            # Exclude common virtual environment and hidden directories
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(('.', '_'))
                and d not in ('venv', 'env', 'node_modules', '__pycache__', '.git')
            ]
            for file in files:
                if file.endswith('.py'):
                    python_files.append(os.path.join(root, file))
        return python_files


    @rate_limited(max_per_minute=20)
    async def _generate_llm_content_with_rate_limit(self, func_name: str, func_info: dict) -> str:
        code_snippet = func_info.get("code_snippet", "No code snippet available.")
        # file_path = func_info.get("file", "N/A") # Already in func_name usually

        prompt_parts = [
            f"Analyze the Python function `{func_name}`.",
            f"Code snippet:\n```python\n{code_snippet}\n```",
            "Provide a concise summary of its purpose and one key suggestion for improvement or refactoring if applicable. If no specific suggestion, state 'No specific refactoring suggestion.'.",
            "Format the response as: Purpose: [Your summary]. Suggestion: [Your suggestion]."
        ]

        if not self.model:
            logger.warning(f"LLM model not available for {func_name}. Skipping LLM content generation.")
            return "LLM model not available. Purpose: Unknown. Suggestion: None."

        try:
            logger.debug(f"Generating LLM content for {func_name} with prompt parts: {prompt_parts}")
            response = await self.model.generate_content_async(prompt_parts)

            generated_text = ""
            if response and hasattr(response, 'text') and response.text:
                generated_text = response.text
            elif response and hasattr(response, 'parts') and response.parts:
                generated_text = "".join(part.text for part in response.parts if hasattr(part, 'text'))

            if not generated_text:
                logger.warning(f"LLM generated empty content for {func_name}")
                generated_text = "LLM generated empty content. Purpose: Unknown. Suggestion: None."
            else:
                logger.debug(f"LLM response for {func_name}: {generated_text}")
            return generated_text
        except Exception as e:
            logger.error(f"Error during LLM content generation for {func_name}: {e}")
            logger.error(traceback.format_exc())
            return f"Error generating LLM content. Purpose: Error. Suggestion: Error ({str(e)})."
        #return "Purpose: Not generated. Suggestion: Not generated."  # Removed to enable LLM calls

    async def analyze_repository(
        self,
        repo_path: str,
        timeout: int = 600,
        clone: bool = False,
        perform_cleanup: bool = True,
    ) -> Dict:
        start_time = time.time()

        # --- FIX: Determine if cloning is needed and pass it down the chain ---
        is_remote = self.is_valid_url(str(repo_path))

        # --- Step 1: Call the parent (EnhancedCallgraphGenerator) ---
        # This will handle everything up to the enhanced static analysis.
        # It populates all necessary attributes.
        # The `perform_cleanup` flag is set to False, as this top-level method will handle it.
        await super().analyze_repository(
            repo_path, timeout, clone=is_remote, perform_cleanup=False
        )

        local_repo_path = self.repo_path
        if not local_repo_path or not os.path.isdir(local_repo_path):
            raise ValueError(f"Repository path is not valid after parent analysis: {local_repo_path}")

        logger.info(f"Research-grade analysis proceeding on path: {local_repo_path}")

        # --- Step 2: Initialize and run the Dynamic Builder ---
        self.dynamic_builder = DynamicCallGraphBuilder(
            framework_hint=self.initial_framework_hint,
            project_root_path=local_repo_path,
        )

        python_files = self._get_python_files(local_repo_path)
        aggregated_graph, files_analyzed = await self._build_dynamic_graph(python_files, start_time, timeout)

        # --- Step 3: Use the dynamically built graph as the definitive result ---
        # The static analysis from the parents was useful for framework detection and
        # populating base_functions, but the dynamic builder gives the most accurate graph.
        final_graph = aggregated_graph

        # --- Step 4: Finalize metadata ---
        analysis_duration = time.time() - start_time
        builder_metadata = self.dynamic_builder.get_analysis_metadata()

        final_metadata = {
            "research_grade_analysis_completed": True,
            "files_analyzed": files_analyzed,
            "total_files_found": len(python_files),
            "analysis_time_seconds": round(analysis_duration, 2),
            "timeout_seconds": timeout,
            **builder_metadata,
            "status": "completed"
        }
        final_graph["metadata"] = final_metadata

        return final_graph

    async def _build_dynamic_graph(self, python_files: List[str], start_time: float, timeout: int) -> Tuple[Dict, int]:
        """
        Builds the dynamic call graph using DynamicCallGraphBuilder, handling file parsing,
        aggregation, and timeout mechanisms.
        """
        aggregated_graph: Dict[str, Any] = {"nodes": [], "links": [], "metadata": {}}
        added_node_ids: Set[str] = set()
        added_link_keys: Set[Tuple[str, str, str]] = set()
        idx = 0
        files_analyzed = 0
        perform_cleanup = True  # Moved to the _build_dynamic_graph for more control
        try:
            logging.info(f"[ResearchCallgraphGenerator] TRY BLOCK START: self.repo_path = {getattr(self, 'repo_path', None)}, perform_cleanup = {perform_cleanup}")
            for file_path_item in python_files:
                elapsed_time = time.time() - start_time
                if elapsed_time > timeout:
                    logging.warning("Analysis timed out.")
                    break
                try:
                    # Read and parse the file to get AST root
                    try:
                        with open(file_path_item, 'r', encoding='utf-8') as f:
                            source_code = f.read()
                        ast_root = ast.parse(source_code, filename=file_path_item)
                    except Exception as e:
                        logging.error(f"Error reading or parsing {file_path_item}: {e}")
                        continue

                    # Call the correct method with AST root and file path
                    # Assuming build_callgraph_for_file is not async, if it is, add await
                    # Also, DynamicCallGraphBuilder might need to be instantiated with project_root_path
                    # Ensure self.dynamic_builder is initialized with project_root_path if needed by its __init__
                    # For now, assuming it's correctly initialized elsewhere or doesn't strictly need it for this call.
                    file_specific_graph = self.dynamic_builder.build_callgraph_for_file(ast_root, file_path_item)
                    if not file_specific_graph:
                        continue
                    files_analyzed += 1
                    # Aggregate nodes and links
                    for node in file_specific_graph.get("nodes", []):
                        node_id = str(node["id"])
                        if node_id not in added_node_ids:
                            aggregated_graph["nodes"].append(node)
                            added_node_ids.add(node_id)
                        else:
                            # Aggregate file occurrences if the node already exists
                            for existing_node in aggregated_graph["nodes"]:
                                if str(existing_node["id"]) == node_id:
                                    if "file_occurrences" not in existing_node["metadata"]:
                                        existing_node["metadata"]["file_occurrences"] = []
                                    if node["metadata"].get("file_path", "") not in existing_node["metadata"].get(
                                        "file_occurrences", []):
                                        existing_node["metadata"]["file_occurrences"].append(node["metadata"].get("file_path", ""))
                                    break
                    for link in file_specific_graph.get("links", []):
                        source_id = str(link["source"])
                        target_id = str(link["target"])
                        link_type = str(link["type"])
                        link_key = (source_id, target_id, link_type)
                        if (
                            source_id not in added_node_ids
                            or target_id not in added_node_ids
                        ):
                            logging.warning(
                                f"Skipping link with missing node: {source_id} -> {target_id} [{link_type}]"
                            )
                            continue
                        if link_key not in added_link_keys:
                            aggregated_graph["links"].append(link)
                            added_link_keys.add(link_key)
                except SyntaxError as e:
                    logging.error(f"Syntax error parsing {file_path_item}: {e}")
                except Exception as e:
                    logging.error(
                        f"Error analyzing {file_path_item} with DynamicCallGraphBuilder: {e}",
                        exc_info=True,
                    )
            else:
                idx += 1
            if hasattr(self.dynamic_builder, "finalize_graph"):
                self.dynamic_builder.finalize_graph(aggregated_graph)
            analysis_duration = time.time() - start_time
            builder_metadata = {}
            if hasattr(self.dynamic_builder, "get_analysis_metadata"):
                builder_metadata = self.dynamic_builder.get_analysis_metadata()
            else:
                builder_metadata["framework_analyzed_as"] = (
                    self.dynamic_builder.framework_detector.get_detected_framework()
                    or self.initial_framework_hint
                )
            final_metadata = {
                "research_grade_analysis_completed": True,
                "files_analyzed": idx,
                "total_files_found": len(python_files),
                "analysis_time_seconds": round(analysis_duration, 2),
                "timeout_seconds": timeout,
                **builder_metadata,
            }
            if elapsed_time > timeout:
                final_metadata["status"] = "timed_out"
            else:
                final_metadata["status"] = "completed"
            aggregated_graph["metadata"] = final_metadata
            if hasattr(self, 'status_log') and self.status_log:
                 final_metadata.setdefault("status_log_from_backend", []).extend(self.status_log)
            logging.info(f"[ResearchCallgraphGenerator] TRY BLOCK END: self.repo_path = {getattr(self, 'repo_path', None)}, perform_cleanup = {perform_cleanup}")
            return aggregated_graph, files_analyzed

        finally:
            current_repo_path = getattr(self, 'repo_path', None)
            logging.info(
                f"[ResearchCallgraphGenerator] FINALLY BLOCK START: "
                f"self.repo_path = {current_repo_path}, "
                f"perform_cleanup = {perform_cleanup}"
            )

            if perform_cleanup and current_repo_path and os.path.exists(current_repo_path) and \
               current_repo_path.startswith(tempfile.gettempdir()):
                logging.info(f"ResearchCallgraphGenerator: Cleaning up temporary directory: {current_repo_path}")
                try:
                    shutil.rmtree(current_repo_path)
                    self.repo_path = None
                except Exception as e:
                    logging.error(f"Error during cleanup of {current_repo_path}: {e}")
            elif perform_cleanup:
                logging.warning(
                    f"ResearchCallgraphGenerator: perform_cleanup is True, but self.repo_path ('{current_repo_path}') "
                    f"is not a valid temp directory to clean or does not exist."
                )

            if hasattr(self.dynamic_builder, 'cleanup'):
                self.dynamic_builder.cleanup()

    async def _enhance_with_research_results(self, basic_result: Dict) -> Dict:
        logging.info(
            "_enhance_with_research_results is effectively handled by DynamicCallGraphBuilder during analyze_repository."
        )
        return basic_result

    def _add_visualization_attributes(self, callgraph: Dict) -> None:
        """
        This method is largely deprecated.
        DynamicCallGraphBuilder should enrich nodes/links with semantic metadata.
        The frontend's DynamicAttributeProvider uses this metadata for styling.
        Kept for minimal backward compatibility or specific overrides if absolutely necessary.
        """
        logging.debug(
            "_add_visualization_attributes called, but most styling should be frontend-driven."
        )
        pass

    def _calculate_type_confidence(self, type_info: Dict) -> float:
        logging.debug(
            "Attempting to calculate type confidence; TypeInferenceEngine should ideally provide this."
        )
        if not type_info:
            return 0.0