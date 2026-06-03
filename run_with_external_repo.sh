#!/bin/bash
set -e

# Parse command line arguments
PHASE=""
STEP=""
MOCK_OUTPUT_DIR=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --phase)
            PHASE="$2"
            shift 2
            ;;
        --step)
            STEP="$2"
            shift 2
            ;;
        --mock-output)
            MOCK_OUTPUT_DIR="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--phase <preprocess|generate|postprocess>] [--step <0|1|2|3>] [--mock-output <dir>]"
            echo ""
            echo "Phase Options:"
            echo "  --phase preprocess   Run only Phase 1 (Sentinel extraction)"
            echo "  --phase generate     Run only Phase 2 (Policy generation)"
            echo "  --phase postprocess  Run only Phase 3 (Deployment)"
            echo ""
            echo "Step Options (only valid with --phase generate or when running all phases):"
            echo "  --step 0             Policy Extraction"
            echo "  --step 1             Requirement Generation"
            echo "  --step 2             Policy Generation"
            echo "  --step 3             Summary Generation"
            echo ""
            echo "Mock Options:"
            echo "  --mock-output <dir>  Skip Phase 2 and use pre-generated output from <dir>"
            echo "                       Example: --mock-output archive_20260525_112836/output"
            echo ""
            echo "If no options specified, runs all phases and all steps."
            echo ""
            echo "Examples:"
            echo "  $0                           # Run all phases, all steps"
            echo "  $0 --phase preprocess        # Extract Sentinel files only"
            echo "  $0 --phase generate          # Generate policies (all steps)"
            echo "  $0 --phase generate --step 2 # Generate policies (step 2 only)"
            echo "  $0 --step 1                  # Run all phases, but only step 1 in Phase 2"
            echo "  $0 --phase postprocess       # Deploy to external repo only"
            echo "  $0 --mock-output archive_20260525_112836/output  # Test with mock data"
            exit 1
            ;;
    esac
done

echo "=========================================="
echo "External Repo Integration Pipeline"
echo "=========================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Preserve environment variables that should not be overridden by .env
PRESERVED_DATA_DIR="${DATA_DIR}"
PRESERVED_INPUT_DIR="${INPUT_DIR}"
PRESERVED_OUTPUT_DIR="${OUTPUT_DIR}"
PRESERVED_INPUT_FILE="${INPUT_FILE}"

# Load environment variables from .env file
# Priority: 1. Current directory, 2. Project root
if [ -f ".env" ]; then
    echo "Loading environment variables from $(pwd)/.env..."
    set -a
    source ".env"
    set +a
    echo "✓ Environment variables loaded"
elif [ -f "${PROJECT_ROOT}/.env" ]; then
    echo "Loading environment variables from ${PROJECT_ROOT}/.env..."
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
    echo "✓ Environment variables loaded"
else
    echo "Error: .env file not found"
    echo "Please create a .env file in current directory or ${PROJECT_ROOT}/"
    echo "with EXTERNAL_REPO_DIR variable."
    exit 1
fi

# Restore preserved variables if they were already set
[ -n "$PRESERVED_DATA_DIR" ] && DATA_DIR="$PRESERVED_DATA_DIR"
[ -n "$PRESERVED_INPUT_DIR" ] && INPUT_DIR="$PRESERVED_INPUT_DIR"
[ -n "$PRESERVED_OUTPUT_DIR" ] && OUTPUT_DIR="$PRESERVED_OUTPUT_DIR"
[ -n "$PRESERVED_INPUT_FILE" ] && INPUT_FILE="$PRESERVED_INPUT_FILE"

# Check required variables
if [ -z "$EXTERNAL_REPO_DIR" ]; then
    echo "Error: EXTERNAL_REPO_DIR not set in .env file"
    echo "Please add: EXTERNAL_REPO_DIR=/path/to/external/repo"
    exit 1
fi

# Check if external repo directory exists
if [ ! -d "$EXTERNAL_REPO_DIR" ]; then
    echo "Error: External repository directory not found: $EXTERNAL_REPO_DIR"
    exit 1
fi

echo "✓ External repository found: $EXTERNAL_REPO_DIR"
echo ""

# Set default values if not set
DATA_DIR="${DATA_DIR:-./data}"

# Ensure DATA_DIR exists before resolving to an absolute path
mkdir -p "$DATA_DIR"

# Resolve DATA_DIR to absolute path from CWD
if [[ "$DATA_DIR" = /* ]]; then
    DATA_DIR_ABS="$DATA_DIR"
else
    DATA_DIR_ABS="$(cd "$DATA_DIR" && pwd)"
fi

# Determine which phases to run
RUN_PREPROCESS=false
RUN_GENERATE=false
RUN_POSTPROCESS=false

if [ -z "$PHASE" ]; then
    # No phase specified, run all
    RUN_PREPROCESS=true
    RUN_GENERATE=true
    RUN_POSTPROCESS=true
else
    case "$PHASE" in
        preprocess)
            RUN_PREPROCESS=true
            ;;
        generate)
            RUN_GENERATE=true
            ;;
        postprocess)
            RUN_POSTPROCESS=true
            ;;
        *)
            echo "Error: Invalid phase '$PHASE'"
            echo "Valid phases: preprocess, generate, postprocess"
            exit 1
            ;;
    esac
fi

# Validate --step option
if [ -n "$STEP" ] && [ "$RUN_PREPROCESS" = true ] && [ "$RUN_GENERATE" = false ]; then
    echo "Error: --step option is only valid with --phase generate or when running all phases"
    exit 1
fi

if [ -n "$STEP" ] && [ "$RUN_POSTPROCESS" = true ] && [ "$RUN_GENERATE" = false ]; then
    echo "Error: --step option is only valid with --phase generate or when running all phases"
    exit 1
fi

# Phase 1: Preprocessing
if [ "$RUN_PREPROCESS" = true ]; then
    echo "=========================================="
    echo "Phase 1: Extract Sentinel files"
    echo "=========================================="
    echo ""

    # Create timestamped directories
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    INPUT_DIR_NAME="input-${TIMESTAMP}"
    OUTPUT_DIR_NAME="output-${TIMESTAMP}"
    
    TEMP_INPUT_DIR="${DATA_DIR_ABS}/${INPUT_DIR_NAME}"
    TEMP_OUTPUT_DIR="${DATA_DIR_ABS}/${OUTPUT_DIR_NAME}"
    SENTINELS_DIR="${TEMP_INPUT_DIR}/sentinels"
    
    mkdir -p "$SENTINELS_DIR"
    mkdir -p "$TEMP_OUTPUT_DIR"

    echo "✓ Created directories:"
    echo "  Input:  $TEMP_INPUT_DIR"
    echo "  Output: $TEMP_OUTPUT_DIR"
    echo ""

    # Copy .sentinel files from external repo
    SENTINEL_COUNT=0
    SKIPPED_COUNT=0
    MOCK_COUNT=0

    while IFS= read -r -d '' sentinel_file; do
        sentinel_dir=$(dirname "$sentinel_file")
        sentinel_basename=$(basename "$sentinel_file" .sentinel)
        
        # Skip mock files in test/ directories
        if [[ "$sentinel_file" == */test/* ]]; then
            echo "⊘ Skipped: $sentinel_file (mock file in test/ directory)"
            MOCK_COUNT=$((MOCK_COUNT + 1))
            continue
        fi
        
        # Skip if policy already exists
        tfpolicy_dir="$sentinel_dir/tfpolicy/$sentinel_basename"
        policy_file="$tfpolicy_dir/$sentinel_basename.policy.hcl"
        
        if [ -f "$policy_file" ]; then
            echo "⊘ Skipped: $sentinel_file (policy already exists)"
            SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
        else
            # Copy to sentinels directory, preserving relative path
            relative_path="${sentinel_file#$EXTERNAL_REPO_DIR/}"
            target_file="$SENTINELS_DIR/$relative_path"
            target_dir=$(dirname "$target_file")
            
            mkdir -p "$target_dir"
            cp "$sentinel_file" "$target_file"
            SENTINEL_COUNT=$((SENTINEL_COUNT + 1))
            echo "✓ Copied: $relative_path"
            
            # Check for mock files in test directory (only if feature flag is enabled)
            if [ "${ENABLE_SENTINEL_MOCK_USE:-false}" = "true" ]; then
                mock_dir="$sentinel_dir/test/$sentinel_basename"
                if [ -d "$mock_dir" ]; then
                    # Copy mock directory
                    relative_mock_path="${mock_dir#$EXTERNAL_REPO_DIR/}"
                    target_mock_dir="$SENTINELS_DIR/$relative_mock_path"
                    
                    mkdir -p "$target_mock_dir"
                    cp -r "$mock_dir"/* "$target_mock_dir/" 2>/dev/null || true
                    
                    if [ "$(ls -A "$target_mock_dir" 2>/dev/null)" ]; then
                        echo "  ✓ Copied mock files: $relative_mock_path"
                    fi
                fi
            fi
        fi
    done < <(find "$EXTERNAL_REPO_DIR" -type f -name "*.sentinel" -print0)

    if [ $SENTINEL_COUNT -eq 0 ]; then
        echo ""
        echo "No new Sentinel files to process."
        echo "  Total files found: $((SENTINEL_COUNT + SKIPPED_COUNT + MOCK_COUNT))"
        echo "  Mock files (in test/): $MOCK_COUNT"
        echo "  Already have policy.hcl: $SKIPPED_COUNT"
        echo "  New files to process: $SENTINEL_COUNT"
        rm -rf "$TEMP_INPUT_DIR" "$TEMP_OUTPUT_DIR"
        exit 0
    fi

    echo ""
    echo "✓ Copied $SENTINEL_COUNT Sentinel files"
    if [ $SKIPPED_COUNT -gt 0 ]; then
        echo "  Skipped $SKIPPED_COUNT files (already have policy.hcl)"
    fi
    if [ $MOCK_COUNT -gt 0 ]; then
        echo "  Skipped $MOCK_COUNT mock files (in test/ directories)"
    fi
    echo ""

    # Copy and process sentinel.hcl if defined
    if [ -n "$SENTINEL_HCL_PATH" ] && [ -f "$SENTINEL_HCL_PATH" ]; then
        echo "Processing sentinel.hcl file..."
        cp "$SENTINEL_HCL_PATH" "$SENTINELS_DIR/sentinel.hcl"
        sed -i.bak 's|source = "[^"]*\/\([^/"]*\.sentinel\)"|source = "\1"|g' "$SENTINELS_DIR/sentinel.hcl"
        rm -f "$SENTINELS_DIR/sentinel.hcl.bak"
        echo "✓ Copied and processed sentinel.hcl"
    fi

    # Generate policy_goal.txt in INPUT_DIR
    POLICY_GOAL_FILE="${TEMP_INPUT_DIR}/policy_goal.txt"
    echo "Generating policy_goal.txt..."
    echo "Generate TF Policy for" > "$POLICY_GOAL_FILE"

    # Add all sentinel files with path relative to DATA_DIR
    # Docker mounts DATA_DIR as /workspace/data, so paths should be relative to that
    # Exclude files in test/ directories (mock files)
    while IFS= read -r -d '' sentinel_file; do
        # Skip if this is a mock file in test/ directory
        if [[ "$sentinel_file" == */test/* ]]; then
            continue
        fi
        
        relative_path="${sentinel_file#$SENTINELS_DIR/}"
        sentinel_line="./data/${INPUT_DIR_NAME}/sentinels/$relative_path"
        
        # Check if mock directory exists for this sentinel (only if feature flag is enabled)
        if [ "${ENABLE_SENTINEL_MOCK_USE:-false}" = "true" ]; then
            sentinel_basename=$(basename "$sentinel_file" .sentinel)
            sentinel_dir=$(dirname "$sentinel_file")
            mock_dir="$sentinel_dir/test/$sentinel_basename"
            
            if [ -d "$mock_dir" ] && [ "$(ls -A "$mock_dir" 2>/dev/null)" ]; then
                # Mock directory exists and is not empty
                relative_mock_path="${mock_dir#$SENTINELS_DIR/}"
                echo "- ${sentinel_line}, Mock Files: ./data/${INPUT_DIR_NAME}/sentinels/$relative_mock_path" >> "$POLICY_GOAL_FILE"
            else
                echo "- ${sentinel_line}" >> "$POLICY_GOAL_FILE"
            fi
        else
            # Feature flag disabled, don't include mock files
            echo "- ${sentinel_line}" >> "$POLICY_GOAL_FILE"
        fi
    done < <(find "$SENTINELS_DIR" -type f -name "*.sentinel" -print0 | sort -z)

    # Add sentinel.hcl reference if exists
    if [ -f "$SENTINELS_DIR/sentinel.hcl" ]; then
        echo "" >> "$POLICY_GOAL_FILE"
        echo "Enforcement level configuration file:" >> "$POLICY_GOAL_FILE"
        echo "./data/${INPUT_DIR_NAME}/sentinels/sentinel.hcl" >> "$POLICY_GOAL_FILE"
    fi

    echo "✓ Generated $POLICY_GOAL_FILE"
    echo ""
else
    # Load latest directories from previous run
    INPUT_DIR_NAME=$(ls -1dt "${DATA_DIR_ABS}"/input-* 2>/dev/null | head -n1 | xargs basename)
    OUTPUT_DIR_NAME=$(ls -1dt "${DATA_DIR_ABS}"/output-* 2>/dev/null | head -n1 | xargs basename)
    
    if [ -z "$INPUT_DIR_NAME" ] || [ -z "$OUTPUT_DIR_NAME" ]; then
        echo "Error: No previous preprocessing run found."
        echo "Please run with --phase preprocess first, or run without --phase to run all phases."
        exit 1
    fi
    
    TEMP_INPUT_DIR="${DATA_DIR_ABS}/${INPUT_DIR_NAME}"
    TEMP_OUTPUT_DIR="${DATA_DIR_ABS}/${OUTPUT_DIR_NAME}"
    POLICY_GOAL_FILE="${TEMP_INPUT_DIR}/policy_goal.txt"
    
    echo "Using directories from previous run:"
    echo "  Input:  $INPUT_DIR_NAME"
    echo "  Output: $OUTPUT_DIR_NAME"
    echo ""
fi

# Phase 2: Generate
if [ "$RUN_GENERATE" = true ]; then
    # Check if using mock output
    if [ -n "$MOCK_OUTPUT_DIR" ]; then
        echo "=========================================="
        echo "Phase 2: SKIPPED (Using Mock Output)"
        echo "=========================================="
        echo ""
        
        # Validate mock output directory
        if [ ! -d "$MOCK_OUTPUT_DIR" ]; then
            echo "Error: Mock output directory not found: $MOCK_OUTPUT_DIR"
            exit 1
        fi
        
        if [ ! -f "$MOCK_OUTPUT_DIR/summary.md" ]; then
            echo "Error: summary.md not found in mock output directory: $MOCK_OUTPUT_DIR"
            exit 1
        fi
        
        echo "Using mock output from: $MOCK_OUTPUT_DIR"
        echo ""
        
        # Copy mock output to TEMP_OUTPUT_DIR
        echo "Copying mock output data..."
        rm -rf "$TEMP_OUTPUT_DIR"
        cp -r "$MOCK_OUTPUT_DIR" "$TEMP_OUTPUT_DIR"
        echo "✓ Mock output copied to: $TEMP_OUTPUT_DIR"
        echo ""
        
    else
        echo "=========================================="
        echo "Phase 2: Run Pipeline"
        echo "=========================================="
        echo ""

        # Set environment variables for run.sh and run_pipeline.py
        export DATA_DIR="$DATA_DIR_ABS"
        export INPUT_DIR="$INPUT_DIR_NAME"
        export OUTPUT_DIR="$OUTPUT_DIR_NAME"
        export INPUT_FILE="policy_goal.txt"

        echo "Running policy generation pipeline..."
        echo "  Data Dir: $DATA_DIR_ABS"
        echo "  Input:    $INPUT_DIR_NAME"
        echo "  Output:   $OUTPUT_DIR_NAME"
        echo "  Policy:   policy_goal.txt"
        
        if [ -n "$STEP" ]; then
            echo "  Step:     $STEP"
        fi
        echo ""

        # Run the pipeline
        if [ -n "$STEP" ]; then
            python3 "${SCRIPT_DIR}/run_pipeline.py" --step "$STEP"
        else
            "${SCRIPT_DIR}/run.sh"
        fi

        echo ""
    fi
fi

# Phase 3: Postprocessing
if [ "$RUN_POSTPROCESS" = true ]; then
    echo "=========================================="
    echo "Phase 3: Deploy to External Repository"
    echo "=========================================="
    echo ""

    # Check if summary.md exists
    summary_file="${TEMP_OUTPUT_DIR}/summary.md"
    if [ ! -f "$summary_file" ]; then
        echo "Error: summary.md not found in $TEMP_OUTPUT_DIR"
        echo "Pipeline may have failed. Please check the logs."
        exit 1
    fi

    # Arrays to track results
    declare -a DEPLOYED_POLICIES
    declare -a FAILED_POLICIES

    # Parse summary.md to get policy status
    while IFS='|' read -r _ policy_name status _ _ _ _; do
        # Skip header and separator lines
        [[ "$policy_name" =~ ^[[:space:]]*Generated[[:space:]]+TF[[:space:]]+Policy[[:space:]]+Name[[:space:]]*$ ]] && continue
        [[ "$policy_name" =~ ^[[:space:]]*-+[[:space:]]*$ ]] && continue
        [[ -z "$policy_name" ]] && continue
        
        # Trim whitespace
        policy_name=$(echo "$policy_name" | xargs)
        status=$(echo "$status" | xargs)
        
        # Normalize policy name
        normalized_policy_name=$(echo "$policy_name" | tr '[:upper:]' '[:lower:]' | tr ' _' '-')
        
        # Check status
        if [[ "$status" == *"Success"* ]] || [[ "$status" == "✅ Success" ]]; then
            policy_found=false
            for policy_dir in "${TEMP_OUTPUT_DIR}"/*/; do
                [ ! -d "$policy_dir" ] && continue
                [ "$(basename "$policy_dir")" = "goals" ] && continue
                
                policy_dir_name=$(basename "$policy_dir")
                normalized_dir_name=$(echo "$policy_dir_name" | tr '[:upper:]' '[:lower:]' | tr ' _' '-')
                
                [ "$normalized_dir_name" != "$normalized_policy_name" ] && continue
                
                # Resolve sentinel path
                report_file="$policy_dir/report.md"
                sentinel_path=""
                sentinel_basename_from_dir=$(echo "$normalized_dir_name" | tr '-' '_')
                
                # First, try to identify the input sentinel directly from input/sentinels
                if [ -d "${TEMP_INPUT_DIR}/sentinels" ]; then
                    matched_sentinel=$(find "${TEMP_INPUT_DIR}/sentinels" -type f \( -name "${normalized_dir_name}.sentinel" -o -name "${sentinel_basename_from_dir}.sentinel" \) | head -n 1)
                    if [ -n "$matched_sentinel" ]; then
                        sentinel_path="${matched_sentinel#${TEMP_INPUT_DIR}/sentinels/}"
                    fi
                fi
                
                # Fallback to report.md if direct lookup failed
                if [ -z "$sentinel_path" ]; then
                    [ ! -f "$report_file" ] && continue
                    sentinel_path=$(grep -o "sentinels/[^[:space:]]*\.sentinel" "$report_file" | head -n 1 | sed 's|sentinels/||')
                    [ -z "$sentinel_path" ] && continue
                fi
                
                # Determine target directory
                sentinel_dir=$(dirname "$sentinel_path")
                sentinel_basename=$(basename "$sentinel_path" .sentinel)
                
                if [ "$sentinel_dir" = "." ]; then
                    target_dir="$EXTERNAL_REPO_DIR/tfpolicy/$sentinel_basename"
                else
                    target_dir="$EXTERNAL_REPO_DIR/$sentinel_dir/tfpolicy/$sentinel_basename"
                fi
                
                mkdir -p "$target_dir"
                
                # Check required files - use dynamic filenames based on policy directory name
                # Find policy and test files that match the directory name (case-insensitive)
                policy_file=""
                policytest_file=""
                
                # Search for files matching the pattern (case-insensitive)
                for file in "$policy_dir"/*.policy.hcl; do
                    if [ -f "$file" ]; then
                        filename=$(basename "$file" .policy.hcl)
                        # Case-insensitive comparison using tr
                        filename_lower=$(echo "$filename" | tr '[:upper:]' '[:lower:]')
                        policy_dir_name_lower=$(echo "$policy_dir_name" | tr '[:upper:]' '[:lower:]')
                        if [ "$filename_lower" = "$policy_dir_name_lower" ]; then
                            policy_file="$file"
                            break
                        fi
                    fi
                done
                
                for file in "$policy_dir"/*.policytest.hcl; do
                    if [ -f "$file" ]; then
                        filename=$(basename "$file" .policytest.hcl)
                        # Case-insensitive comparison using tr
                        filename_lower=$(echo "$filename" | tr '[:upper:]' '[:lower:]')
                        policy_dir_name_lower=$(echo "$policy_dir_name" | tr '[:upper:]' '[:lower:]')
                        if [ "$filename_lower" = "$policy_dir_name_lower" ]; then
                            policytest_file="$file"
                            break
                        fi
                    fi
                done
                
                if [ -z "$policy_file" ] || [ -z "$policytest_file" ] || [ ! -f "$policy_dir/main.tf" ] || [ ! -f "$policy_dir/report.md" ]; then
                    FAILED_POLICIES+=("$sentinel_path (missing files)")
                    policy_found=true
                    break
                fi
                
                echo "📦 Deploying: $policy_dir_name → tfpolicy/$sentinel_basename/"
                
                cp "$policy_file" "$target_dir/$sentinel_basename.policy.hcl"
                echo "  ✓ $sentinel_basename.policy.hcl"
                
                cp "$policytest_file" "$target_dir/$sentinel_basename.policytest.hcl"
                echo "  ✓ $sentinel_basename.policytest.hcl"
                
                cp "$policy_dir/main.tf" "$target_dir/$sentinel_basename.tf"
                echo "  ✓ $sentinel_basename.tf"
                
                cp "$policy_dir/report.md" "$target_dir/$sentinel_basename.report.md"
                echo "  ✓ $sentinel_basename.report.md"
                
                DEPLOYED_POLICIES+=("$sentinel_path")
                policy_found=true
                echo ""
                break
            done
        fi
    done < <(grep -A 1000 "^| Generated TF Policy Name" "$summary_file" | grep "^|")

    echo "=========================================="
    echo "✓ Deployment Complete!"
    echo "=========================================="
    echo ""
    echo "Summary:"
    echo "  Deployed: ${#DEPLOYED_POLICIES[@]} policies"
    echo "  Failed: ${#FAILED_POLICIES[@]} policies"
    echo "  Target: $EXTERNAL_REPO_DIR"
    echo ""

    if [ ${#DEPLOYED_POLICIES[@]} -gt 0 ]; then
        echo "Successfully Deployed Policies:"
        for policy in "${DEPLOYED_POLICIES[@]}"; do
            echo "  ✓ $policy"
        done
        echo ""
    fi

    if [ ${#FAILED_POLICIES[@]} -gt 0 ]; then
        echo "Failed Policies (NOT deployed):"
        for policy in "${FAILED_POLICIES[@]}"; do
            echo "  ✗ $policy"
        done
        echo ""
    fi

    echo "Next steps:"
    echo "  1. Review generated policies in: $EXTERNAL_REPO_DIR"
    echo "  2. Commit and push changes:"
    echo "     cd $EXTERNAL_REPO_DIR"
    echo "     git add tfpolicy/"
    echo "     git commit -m 'Add generated TF policies'"
    echo "     git push"
    echo ""
fi

# Made with Bob
