import os
import yaml
from tree_sitter import Language, Parser
from tree_sitter_languages import get_language

# --- Setup Tree-sitter Parser for JavaScript ---
JS_LANGUAGE = get_language('javascript')
parser = Parser()
parser.set_language(JS_LANGUAGE)

def get_node_text(node, source_bytes):
    """Helper to get the text content of a tree-sitter node."""
    return source_bytes[node.start_byte:node.end_byte].decode('utf-8')

def parse_js_file(file_path):
    """
    Parses a JavaScript file and extracts structural information
    in the specified YAML format.
    """
    try:
        with open(file_path, 'rb') as f:
            source_bytes = f.read()
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
        return None

    tree = parser.parse(source_bytes)
    root_node = tree.root_node

    file_data = {
        "filename": os.path.basename(file_path),
        "language": "javascript",
        "classes": [],
        "file_level_methods": [],
        "imports": [],  # Will contain all imports (internal/external)
        "external_dependencies": [], # Only external dependencies with potential versions
        "external_references": [] # List of unique external module names referenced
    }

    # Helper set to keep track of unique external dependency names for `external_references`
    unique_external_refs_in_file = set()

    # --- Traverse the AST ---
    for node in root_node.children:
        # --- Imports and Requires ---
        if node.type == 'import_statement':
            # import defaultExport from "module-name";
            # import * as name from "module-name";
            # import { export1 } from "module-name";
            # import { export1 as alias1 } from "module-name";
            # import { export1 , export2 } from "module-name";
            # import "module-name"; (side-effect import)
            source_node = node.child_by_field_name('source')
            if source_node:
                module_path = get_node_text(source_node).strip("'\"")
                import_info = {"name": module_path}

                if module_path.startswith('.') or module_path.startswith('/'):
                    import_info["type"] = "internal"
                else:
                    import_info["type"] = "external"
                    # Extract package name for external dependencies (e.g., 'lodash/get' -> 'lodash')
                    package_name = module_path.split('/')[0]
                    if package_name.startswith('@'): # Handle scoped packages like @angular/core
                        package_name = '/'.join(module_path.split('/')[:2])
                    
                    file_data["external_dependencies"].append({
                        "name": package_name,
                        "type": "instance", # Assuming 'instance' for now, could be 'type' if using TS
                        "version": "UNKNOWN" # Placeholder: Requires package.json lookup
                    })
                    unique_external_refs_in_file.add(package_name)
                
                file_data["imports"].append(import_info)

        elif node.type == 'variable_declarator' and node.child_by_field_name('value') and \
             node.child_by_field_name('value').type == 'call_expression' and \
             get_node_text(node.child_by_field_name('value').child_by_field_name('function'), source_bytes) == 'require':
            # const myModule = require('module-name');
            arg_node = node.child_by_field_name('value').child_by_field_name('arguments').child(0)
            if arg_node and arg_node.type in ['string', 'template_string']:
                module_path = get_node_text(arg_node).strip("'\"`")
                import_info = {"name": module_path}

                if module_path.startswith('.') or module_path.startswith('/'):
                    import_info["type"] = "internal"
                else:
                    import_info["type"] = "external"
                    package_name = module_path.split('/')[0]
                    if package_name.startswith('@'):
                        package_name = '/'.join(module_path.split('/')[:2])

                    file_data["external_dependencies"].append({
                        "name": package_name,
                        "type": "instance",
                        "version": "UNKNOWN"
                    })
                    unique_external_refs_in_file.add(package_name)

                file_data["imports"].append(import_info)
        elif node.type == 'expression_statement' and node.child(0) and node.child(0).type == 'call_expression' and \
             get_node_text(node.child(0).child_by_field_name('function'), source_bytes) == 'require' and \
             node.child(0).child_by_field_name('arguments') and \
             node.child(0).child_by_field_name('arguments').child(0) and \
             node.child(0).child_by_field_name('arguments').child(0).type in ['string', 'template_string']:
            # require('module-name'); (side-effect require)
            arg_node = node.child(0).child_by_field_name('arguments').child(0)
            module_path = get_node_text(arg_node).strip("'\"`")
            import_info = {"name": module_path}
            
            if module_path.startswith('.') or module_path.startswith('/'):
                import_info["type"] = "internal"
            else:
                import_info["type"] = "external"
                package_name = module_path.split('/')[0]
                if package_name.startswith('@'):
                    package_name = '/'.join(module_path.split('/')[:2])
                file_data["external_dependencies"].append({
                    "name": package_name,
                    "type": "instance",
                    "version": "UNKNOWN"
                })
                unique_external_refs_in_file.add(package_name)
            file_data["imports"].append(import_info)

        # --- Classes ---
        elif node.type == 'class_declaration' or (node.type == 'lexical_declaration' and node.child(1) and node.child(1).type == 'class_declaration'):
            class_node = node if node.type == 'class_declaration' else node.child(1)
            class_name = get_node_text(class_node.child_by_field_name('name'), source_bytes) if class_node.child_by_field_name('name') else 'AnonymousClass'
            bases = []
            if class_node.child_by_field_name('super_class'):
                bases.append(get_node_text(class_node.child_by_field_name('super_class'), source_bytes))

            class_info = {
                "name": class_name,
                "bases": bases,
                "docstring": "", # Placeholder, more advanced JSDoc parsing needed
                "methods": [],
                "static_methods": [],
                "class_methods": [] # JS doesn't have direct 'class methods' like Python, but static methods serve a similar purpose
            }

            # Find docstring (simple heuristic: look for multiline comment before class)
            prev_sibling = class_node.prev_sibling
            if prev_sibling and prev_sibling.type == 'comment' and '/**' in get_node_text(prev_sibling, source_bytes):
                class_info['docstring'] = get_node_text(prev_sibling, source_bytes).strip()

            body_node = class_node.child_by_field_name('body')
            if body_node:
                for method_node in body_node.children:
                    if method_node.type == 'method_definition':
                        method_name_node = method_node.child_by_field_name('name')
                        method_name = get_node_text(method_name_node, source_bytes) if method_name_node else 'anonymous_method'

                        method_info = {
                            "name": method_name,
                            "parameters": [],
                            "returns": "None", # Hard to infer without TS or advanced analysis
                            "docstring": "",
                            "external_references": sorted(list(unique_external_refs_in_file)), # List all imported external modules
                            "line_start": method_node.start_point[0] + 1,
                            "line_end": method_node.end_point[0] + 1
                        }

                        # Parameters
                        parameters_node = method_node.child_by_field_name('parameters')
                        if parameters_node:
                            for param in parameters_node.children:
                                if param.type == 'identifier':
                                    method_info['parameters'].append(get_node_text(param, source_bytes))
                                # Handle destructuring, rest parameters etc. (more complex)

                        # Docstring for method (simple heuristic)
                        prev_sibling_method = method_node.prev_sibling
                        if prev_sibling_method and prev_sibling_method.type == 'comment' and '/**' in get_node_text(prev_sibling_method, source_bytes):
                            method_info['docstring'] = get_node_text(prev_sibling_method, source_bytes).strip()

                        if 'static' in [get_node_text(c, source_bytes) for c in method_node.children if c.type == 'identifier' and c.text.decode('utf-8') == 'static']:
                            class_info["static_methods"].append(method_info)
                        else:
                            class_info["methods"].append(method_info)
            file_data["classes"].append(class_info)

        # --- File-level Functions (Function Declarations and Arrow Functions assigned to variables) ---
        elif node.type == 'function_declaration':
            function_name = get_node_text(node.child_by_field_name('name'), source_bytes) if node.child_by_field_name('name') else 'anonymous_function'
            
            function_info = {
                "name": function_name,
                "parameters": [],
                "returns": "None",
                "docstring": "",
                "external_references": sorted(list(unique_external_refs_in_file)),
                "line_start": node.start_point[0] + 1,
                "line_end": node.end_point[0] + 1
            }

            parameters_node = node.child_by_field_name('parameters')
            if parameters_node:
                for param in parameters_node.children:
                    if param.type == 'identifier':
                        function_info['parameters'].append(get_node_text(param, source_bytes))

            prev_sibling = node.prev_sibling
            if prev_sibling and prev_sibling.type == 'comment' and '/**' in get_node_text(prev_sibling, source_bytes):
                function_info['docstring'] = get_node_text(prev_sibling, source_bytes).strip()

            file_data["file_level_methods"].append(function_info)
        
        elif node.type == 'lexical_declaration' or node.type == 'variable_declaration':
            # Look for arrow functions assigned to variables: const myFunction = () => {...}
            for declarator in node.children:
                if declarator.type == 'variable_declarator':
                    name_node = declarator.child_by_field_name('name')
                    value_node = declarator.child_by_field_name('value')
                    
                    if name_node and value_node and (value_node.type == 'arrow_function' or value_node.type == 'function_expression'):
                        function_name = get_node_text(name_node, source_bytes)
                        
                        function_info = {
                            "name": function_name,
                            "parameters": [],
                            "returns": "None",
                            "docstring": "",
                            "external_references": sorted(list(unique_external_refs_in_file)),
                            "line_start": node.start_point[0] + 1,
                            "line_end": node.end_point[0] + 1
                        }

                        parameters_node = value_node.child_by_field_name('parameters')
                        if parameters_node:
                            for param in parameters_node.children:
                                if param.type == 'identifier':
                                    function_info['parameters'].append(get_node_text(param, source_bytes))
                        
                        prev_sibling = node.prev_sibling
                        if prev_sibling and prev_sibling.type == 'comment' and '/**' in get_node_text(prev_sibling, source_bytes):
                            function_info['docstring'] = get_node_text(prev_sibling, source_bytes).strip()

                        file_data["file_level_methods"].append(function_info)

    file_data["external_references"] = sorted(list(unique_external_refs_in_file))
    # Remove duplicate external dependencies by name, keeping the first encountered (or merging if needed)
    seen_external_deps = {}
    unique_external_deps_list = []
    for dep in file_data["external_dependencies"]:
        if dep["name"] not in seen_external_deps:
            seen_external_deps[dep["name"]] = True
            unique_external_deps_list.append(dep)
    file_data["external_dependencies"] = unique_external_deps_list


    return {"files": [file_data]}

def generate_project_structure_yaml(project_root_dir, output_yaml_path):
    """
    Traverses a JavaScript project directory, parses relevant files,
    and generates a combined YAML structure.
    """
    project_data = {"files": []}
    
    # Exclude directories
    excluded_dirs = ['.git', 'node_modules', 'build', 'dist', 'venv', '__pycache__']
    # Exclude file extensions (e.g., test files, minified files)
    excluded_extensions = ['.min.js', '.test.js', '.spec.js']

    for root, dirs, files in os.walk(project_root_dir):
        # Modify dirs in-place to skip excluded directories
        dirs[:] = [d for d in dirs if d not in excluded_dirs]

        for file in files:
            if file.endswith('.js') and not any(file.endswith(ext) for ext in excluded_extensions):
                file_path = os.path.join(root, file)
                print(f"Processing: {file_path}")
                parsed_data = parse_js_file(file_path)
                if parsed_data:
                    project_data["files"].extend(parsed_data["files"])

    with open(output_yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump(project_data, f, indent=2, sort_keys=False)
    print(f"YAML structure generated at: {output_yaml_path}")

# --- Example Usage ---
if __name__ == "__main__":
    # Create a dummy JavaScript project for testing
    dummy_project_dir = "dummy_js_project"
    os.makedirs(dummy_project_dir, exist_ok=True)

    # Example 1: Simple class and function
    with open(os.path.join(dummy_project_dir, "example.js"), "w") as f:
        f.write("""
/**
 * @file This is an example JavaScript file.
 */
import React from 'react';
import { someUtil } from './utils/helpers';
const path = require('path');
require('dotenv').config(); // side-effect require

/**
 * This is MyClass.
 * It demonstrates methods, static methods.
 * @extends BaseClass
 */
class MyClass extends BaseClass {
    /**
     * Constructor for MyClass.
     * @param {string} name - The name of the instance.
     */
    constructor(name) {
        super();
        this.name = name;
    }

    /**
     * An instance method.
     * @param {number} value - A value.
     * @returns {string} A processed string.
     */
    myMethod(value) {
        console.log(`Hello, ${this.name} with value: ${value}`);
        return `Processed: ${value}`;
    }

    /**
     * A static method example.
     * @param {any} data
     * @returns {boolean}
     */
    static staticMethodExample(data) {
        return !!data;
    }
}

/**
 * A global function example.
 * @param {string} param1 - First parameter.
 * @param {boolean} param2 - Second parameter.
 * @returns {string} Concatenated string.
 */
function globalFunctionExample(param1, param2) {
    const result = `${param1}-${param2}`;
    return result;
}

const myArrowFunction = (a, b) => {
    // This is an arrow function
    const sum = a + b;
    return sum;
};

export default MyClass;
        """)

    # Example 2: Another module with internal/external mix
    os.makedirs(os.path.join(dummy_project_dir, "utils"), exist_ok=True)
    with open(os.path.join(dummy_project_dir, "utils", "helpers.js"), "w") as f:
        f.write("""
// helpers.js
import axios from 'axios';
import _ from 'lodash';
import { anotherHelper } from '../anotherFile';

export function someUtil(data) {
    console.log(_.isEmpty(data));
    return axios.get('/api/data');
}
        """)
    
    with open(os.path.join(dummy_project_dir, "anotherFile.js"), "w") as f:
        f.write("""
// anotherFile.js
export function anotherHelper() {
    return 'Hello from another helper';
}
        """)

    output_yaml_file = "project_structure.yaml"
    generate_project_structure_yaml(dummy_project_dir, output_yaml_file)

    # You can inspect the generated YAML file
    # with open(output_yaml_file, 'r') as f:
    #     print("\n--- Generated YAML ---")
    #     print(f.read())
    # print("--------------------")

    # Clean up dummy project
    import shutil
    shutil.rmtree(dummy_project_dir)
    print(f"Cleaned up {dummy_project_dir}")