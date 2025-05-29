import os
import ast
import logging
from typing import Dict, List, Set, Optional, Tuple, Any
import time
import shutil
from .enhanced_callgraph import EnhancedCallgraphGenerator
from .dynamic_callgraph_builder import DynamicCallGraphBuilder


class ResearchCallgraphGenerator(EnhancedCallgraphGenerator):
    def __init__(self, framework: str = "generic", max_depth: int = 8):
        super().__init__()
        self.max_depth = max_depth
        self.dynamic_builder: Optional[DynamicCallGraphBuilder] = None
        self.initial_framework_hint = framework

    async def analyze_repository(
        self,
        repo_path: str,
        timeout: int = 600,
        clone: bool = False,
        perform_cleanup: bool = True,
    ) -> Dict:
        start_time = time.time()
        try:
            await super().analyze_repository(
                repo_path, timeout, clone, perform_cleanup=False
            )
            local_repo_path = self.repo_path
            if not local_repo_path or not os.path.isdir(local_repo_path):
                logging.error(
                    f"Repository path '{local_repo_path}' is not a valid directory after attempting to prepare it. Original path: {repo_path}"
                )
                return {
                    "nodes": [],
                    "links": [],
                    "metadata": {
                        "error": "Invalid repository path after setup",
                        "status": "error",
                    },
                }
            logging.info(
                f"ResearchCallgraphGenerator proceeding with analysis on local path: {local_repo_path}"
            )
            self.dynamic_builder = DynamicCallGraphBuilder(
                framework_hint=self.initial_framework_hint,
                project_root_path=local_repo_path,
            )
            python_files = []
            for root, _, files_in_dir in os.walk(local_repo_path):
                for file_item in files_in_dir:
                    if file_item.endswith(".py"):
                        path_parts = os.path.normpath(root).split(os.sep)
                        if any(
                            part
                            in [
                                ".git",
                                ".hg",
                                ".svn",
                                "node_modules",
                                "__pycache__",
                                "migrations",
                            ]
                            or part.endswith((".egg-info", ".dist-info", ".cache"))
                            or (
                                "site-packages" in path_parts
                                or "dist-packages" in path_parts
                            )
                            or (
                                part in ["venv", "env"]
                                and local_repo_path
                                == os.path.dirname(os.path.join(root, part))
                            )
                            for part in path_parts
                        ):
                            continue
                        python_files.append(os.path.join(root, file_item))
            if not python_files:
                logging.warning(
                    f"No Python files found for analysis in {local_repo_path}. Check repository structure and filters."
                )
                return {
                    "nodes": [],
                    "links": [],
                    "metadata": {
                        "status": "completed_no_files",
                        "files_analyzed": 0,
                        "total_files_found": 0,
                    },
                }
            aggregated_graph: Dict[str, Any] = {
                "nodes": [],
                "links": [],
                "metadata": {},
            }
            added_node_ids: Set[str] = set()
            added_link_keys: Set[Tuple[str, str, str]] = set()
            idx = 0
            elapsed_time = 0.0
            for idx, file_path_item in enumerate(python_files):
                elapsed_time = time.time() - start_time
                if elapsed_time > timeout:
                    logging.warning(
                        f"Timeout reached processing files. Processed {idx}/{len(python_files)}."
                    )
                    break
                content = self._safe_read_file(file_path_item)
                if not content:
                    logging.warning(f"Could not read or empty file: {file_path_item}")
                    continue
                try:
                    ast_tree = ast.parse(content, filename=file_path_item)
                    file_specific_graph = self.dynamic_builder.build_callgraph_for_file(
                        ast_tree, file_path=file_path_item
                    )
                    for node in file_specific_graph.get("nodes", []):
                        node_id = node["id"]
                        if node_id not in added_node_ids:
                            aggregated_graph["nodes"].append(node)
                            added_node_ids.add(node_id)
                        else:
                            for existing_node in aggregated_graph["nodes"]:
                                if existing_node["id"] == node_id:
                                    if existing_node.get("metadata", {}).get(
                                        "is_placeholder", False
                                    ) and not node.get("metadata", {}).get(
                                        "is_placeholder", False
                                    ):
                                        existing_node["metadata"] = node.get(
                                            "metadata", {}
                                        )
                                    if "file_path" in node.get("metadata", {}) and node[
                                        "metadata"
                                    ]["file_path"] != existing_node.get(
                                        "metadata", {}
                                    ).get(
                                        "file_path", ""
                                    ):
                                        if (
                                            "file_occurrences"
                                            not in existing_node["metadata"]
                                        ):
                                            existing_node["metadata"][
                                                "file_occurrences"
                                            ] = [
                                                existing_node["metadata"].get(
                                                    "file_path", ""
                                                )
                                            ]
                                        existing_node["metadata"][
                                            "file_occurrences"
                                        ].append(node["metadata"].get("file_path", ""))
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
            return aggregated_graph
        finally:
            if (
                perform_cleanup
                and hasattr(self, "cleanup_needed")
                and self.cleanup_needed
                and hasattr(self, "temp_dir")
                and self.temp_dir
                and os.path.exists(self.temp_dir)
            ):
                try:
                    logging.info(
                        f"ResearchCallgraphGenerator performing cleanup of temporary directory: {self.temp_dir}"
                    )
                    shutil.rmtree(self.temp_dir)
                    logging.info(f"Successfully cleaned up {self.temp_dir}")
                except Exception as e:
                    logging.error(
                        f"Error during ResearchCallgraphGenerator cleanup of {self.temp_dir}: {e}"
                    )

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
        return type_info.get("confidence", 0.5)
