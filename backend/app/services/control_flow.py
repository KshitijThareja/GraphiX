import ast
from typing import Dict, List, Set, Optional, Tuple, Any, Union
import logging

logger = logging.getLogger(__name__)


class CFGBlock:
    def __init__(self, id: int):
        self.id = id
        self.statements: List[ast.AST] = []
        self.predecessors: Set["CFGBlock"] = set()
        self.successors: Set["CFGBlock"] = set()
        self.in_vars: Set[str] = set()
        self.out_vars: Set[str] = set()
        self.entry_point = False
        self.exit_point = False
        self.condition: Optional[ast.AST] = None

    def add_statement(self, statement: ast.AST) -> None:
        self.statements.append(statement)

    def add_successor(
        self, block: "CFGBlock", condition: Optional[ast.AST] = None
    ) -> None:
        self.successors.add(block)
        block.predecessors.add(self)
        if condition:
            block.condition = condition

    def __repr__(self) -> str:
        return (
            f"CFGBlock(id={self.id}, statements={len(self.statements)}, "
            f"predecessors={len(self.predecessors)}, successors={len(self.successors)})"
        )


class ControlFlowGraph:
    def __init__(self):
        self.blocks: List[CFGBlock] = []
        self.entry_block: Optional[CFGBlock] = None
        self.exit_block: Optional[CFGBlock] = None
        self.current_block: Optional[CFGBlock] = None
        self._block_counter = 0

    def create_block(self) -> CFGBlock:
        block = CFGBlock(self._block_counter)
        self._block_counter += 1
        self.blocks.append(block)
        return block

    def set_entry_block(self, block: CFGBlock) -> None:
        self.entry_block = block
        block.entry_point = True
        self.current_block = block

    def set_exit_block(self, block: CFGBlock) -> None:
        self.exit_block = block
        block.exit_point = True

    def add_statement(self, statement: ast.AST) -> None:
        if not self.current_block:
            self.current_block = self.create_block()
            if not self.entry_block:
                self.set_entry_block(self.current_block)
        self.current_block.add_statement(statement)

    def connect_blocks(
        self, source: CFGBlock, target: CFGBlock, condition: Optional[ast.AST] = None
    ) -> None:
        source.add_successor(target, condition)

    def __repr__(self) -> str:
        return f"ControlFlowGraph(blocks={len(self.blocks)})"


class CFGBuilder:
    def __init__(self):
        self.cfg = ControlFlowGraph()
        self.break_stack: List[List[CFGBlock]] = []
        self.continue_stack: List[List[CFGBlock]] = []
        self.current_loop_entry: List[CFGBlock] = []

    def build(self, node: Union[ast.AST, List[ast.AST]]) -> ControlFlowGraph:
        self.cfg.set_entry_block(self.cfg.create_block())
        exit_block = self.cfg.create_block()
        self.cfg.set_exit_block(exit_block)
        if isinstance(node, list):
            self._process_body(node)
        else:
            self._process_node(node)
        if self.cfg.current_block and self.cfg.current_block != exit_block:
            self.cfg.connect_blocks(self.cfg.current_block, exit_block)
        return self.cfg

    def _process_body(self, body: List[ast.AST]) -> None:
        for statement in body:
            self._process_node(statement)

    def _process_node(self, node: ast.AST) -> None:
        if isinstance(node, ast.If):
            self._process_if(node)
        elif isinstance(node, ast.For) or isinstance(node, ast.AsyncFor):
            self._process_for(node)
        elif isinstance(node, ast.While):
            self._process_while(node)
        elif isinstance(node, ast.Try):
            self._process_try(node)
        elif isinstance(node, ast.Break):
            self._process_break()
        elif isinstance(node, ast.Continue):
            self._process_continue()
        elif isinstance(node, ast.Return):
            self._process_return(node)
        elif isinstance(node, ast.Raise):
            self._process_raise(node)
        elif isinstance(node, ast.With) or isinstance(node, ast.AsyncWith):
            self._process_with(node)
        else:
            self.cfg.add_statement(node)

    def _process_if(self, node: ast.If) -> None:
        before_if = self.cfg.current_block
        true_block = self.cfg.create_block()
        false_block = self.cfg.create_block()
        after_if = self.cfg.create_block()
        self.cfg.connect_blocks(before_if, true_block, node.test)
        if hasattr(ast, "UnaryOp"):
            not_test = ast.UnaryOp(op=ast.Not(), operand=node.test)
        else:
            not_test = ast.Not(node.test)
        self.cfg.connect_blocks(before_if, false_block, not_test)
        self.cfg.current_block = true_block
        self._process_body(node.body)
        true_end = self.cfg.current_block
        self.cfg.current_block = false_block
        if node.orelse:
            self._process_body(node.orelse)
        false_end = self.cfg.current_block
        if true_end and true_end != after_if:
            self.cfg.connect_blocks(true_end, after_if)
        if false_end and false_end != after_if:
            self.cfg.connect_blocks(false_end, after_if)
        self.cfg.current_block = after_if

    def _process_for(self, node: Union[ast.For, ast.AsyncFor]) -> None:
        loop_header = self.cfg.create_block()
        loop_body = self.cfg.create_block()
        after_loop = self.cfg.create_block()
        self.cfg.connect_blocks(self.cfg.current_block, loop_header)
        loop_header.add_statement(node)
        self.cfg.connect_blocks(loop_header, loop_body, node.iter)
        self.cfg.connect_blocks(loop_header, after_loop)
        self.break_stack.append([after_loop])
        self.continue_stack.append([loop_header])
        self.current_loop_entry.append(loop_header)
        self.cfg.current_block = loop_body
        self._process_body(node.body)
        if node.orelse:
            else_block = self.cfg.create_block()
            self.cfg.connect_blocks(self.cfg.current_block, else_block)
            self.cfg.current_block = else_block
            self._process_body(node.orelse)
            self.cfg.connect_blocks(self.cfg.current_block, after_loop)
        else:
            self.cfg.connect_blocks(self.cfg.current_block, loop_header)
        self.break_stack.pop()
        self.continue_stack.pop()
        self.current_loop_entry.pop()
        self.cfg.current_block = after_loop

    def _process_while(self, node: ast.While) -> None:
        loop_cond = self.cfg.create_block()
        loop_body = self.cfg.create_block()
        after_loop = self.cfg.create_block()
        self.cfg.connect_blocks(self.cfg.current_block, loop_cond)
        loop_cond.add_statement(node)
        self.cfg.connect_blocks(loop_cond, loop_body, node.test)
        if hasattr(ast, "UnaryOp"):
            not_test = ast.UnaryOp(op=ast.Not(), operand=node.test)
        else:
            not_test = ast.Not(node.test)
        self.cfg.connect_blocks(loop_cond, after_loop, not_test)
        self.break_stack.append([after_loop])
        self.continue_stack.append([loop_cond])
        self.current_loop_entry.append(loop_cond)
        self.cfg.current_block = loop_body
        self._process_body(node.body)
        if node.orelse:
            else_block = self.cfg.create_block()
            self.cfg.connect_blocks(self.cfg.current_block, else_block)
            self.cfg.current_block = else_block
            self._process_body(node.orelse)
            self.cfg.connect_blocks(self.cfg.current_block, after_loop)
        else:
            self.cfg.connect_blocks(self.cfg.current_block, loop_cond)
        self.break_stack.pop()
        self.continue_stack.pop()
        self.current_loop_entry.pop()
        self.cfg.current_block = after_loop

    def _process_try(self, node: ast.Try) -> None:
        try_block = self.cfg.create_block()
        handler_blocks = [self.cfg.create_block() for _ in node.handlers]
        else_block = self.cfg.create_block() if node.orelse else None
        finally_block = self.cfg.create_block() if node.finalbody else None
        after_try = self.cfg.create_block()
        self.cfg.connect_blocks(self.cfg.current_block, try_block)
        self.cfg.current_block = try_block
        self._process_body(node.body)
        if node.orelse:
            self.cfg.connect_blocks(self.cfg.current_block, else_block)
        for i, handler in enumerate(node.handlers):
            exc_type = handler.type
            handler_block = handler_blocks[i]
            self.cfg.connect_blocks(try_block, handler_block, exc_type)
            self.cfg.current_block = handler_block
            self._process_body(handler.body)
            if finally_block:
                self.cfg.connect_blocks(self.cfg.current_block, finally_block)
            else:
                self.cfg.connect_blocks(self.cfg.current_block, after_try)
        if else_block:
            self.cfg.current_block = else_block
            self._process_body(node.orelse)
            if finally_block:
                self.cfg.connect_blocks(self.cfg.current_block, finally_block)
            else:
                self.cfg.connect_blocks(self.cfg.current_block, after_try)
        if finally_block:
            self.cfg.current_block = finally_block
            self._process_body(node.finalbody)
            self.cfg.connect_blocks(self.cfg.current_block, after_try)
        self.cfg.current_block = after_try

    def _process_break(self) -> None:
        if not self.break_stack:
            logger.warning("Break statement outside of a loop")
            return
        self.cfg.add_statement(ast.Break())
        for target in self.break_stack[-1]:
            self.cfg.connect_blocks(self.cfg.current_block, target)
        self.cfg.current_block = self.cfg.create_block()

    def _process_continue(self) -> None:
        if not self.continue_stack:
            logger.warning("Continue statement outside of a loop")
            return
        self.cfg.add_statement(ast.Continue())
        for target in self.continue_stack[-1]:
            self.cfg.connect_blocks(self.cfg.current_block, target)
        self.cfg.current_block = self.cfg.create_block()

    def _process_return(self, node: ast.Return) -> None:
        self.cfg.add_statement(node)
        self.cfg.connect_blocks(self.cfg.current_block, self.cfg.exit_block)
        self.cfg.current_block = self.cfg.create_block()

    def _process_raise(self, node: ast.Raise) -> None:
        self.cfg.add_statement(node)
        self.cfg.current_block = self.cfg.create_block()

    def _process_with(self, node: Union[ast.With, ast.AsyncWith]) -> None:
        self.cfg.add_statement(node)
        self._process_body(node.body)


class FlowSensitiveAnalyzer:
    def __init__(self):
        self.cfg_builder = CFGBuilder()

    def analyze_function(
        self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    ) -> ControlFlowGraph:
        cfg = self.cfg_builder.build(node.body)
        self._analyze_data_flow(cfg)
        return cfg

    def _analyze_data_flow(self, cfg: ControlFlowGraph) -> None:
        for block in cfg.blocks:
            block.in_vars = set()
            block.out_vars = set()
        changed = True
        while changed:
            changed = False
            for block in cfg.blocks:
                if block.entry_point:
                    continue
                old_in = block.in_vars.copy()
                block.in_vars = set()
                for pred in block.predecessors:
                    block.in_vars.update(pred.out_vars)
                if old_in != block.in_vars:
                    changed = True
                old_out = block.out_vars.copy()
                block.out_vars = self._process_block_variables(
                    block, block.in_vars.copy()
                )
                if old_out != block.out_vars:
                    changed = True

    def _process_block_variables(self, block: CFGBlock, in_vars: Set[str]) -> Set[str]:
        out_vars = in_vars.copy()
        for stmt in block.statements:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        out_vars.add(target.id)
                    elif isinstance(target, (ast.Tuple, ast.List)) and hasattr(
                        target, "elts"
                    ):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name):
                                out_vars.add(elt.id)
            elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
                out_vars.add(stmt.target.id)
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                for item in stmt.items:
                    if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                        out_vars.add(item.optional_vars.id)
            elif isinstance(stmt, (ast.For, ast.AsyncFor)) and isinstance(
                stmt.target, ast.Name
            ):
                out_vars.add(stmt.target.id)
            elif isinstance(
                stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                out_vars.add(stmt.name)
        return out_vars
