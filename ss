<!-- Create new lab? -->
<div class="control-group">
  <label class="control-label">Create new lab?</label>
  <div class="controls">
    <label class="radio-inline" style="margin-right: 15px;">
      <input type="radio" ng-model="config.create_new_lab" value="yes" />
      Yes
    </label>
    <label class="radio-inline">
      <input type="radio" ng-model="config.create_new_lab" value="no" />
      No
    </label>
  </div>
</div>

<!-- New lab name (shown only if Yes) -->
<div class="control-group" ng-if="config.create_new_lab === 'yes'">
  <label class="control-label">Name your lab</label>
  <div class="controls">
    <input type="text"
           ng-model="config.lab"
           class="form-control"
           placeholder="e.g. Welcome_Call" />
    <span class="help-inline" ng-if="labNameError" style="color: #c9302c;">
      {{ labNameError }}
    </span>
  </div>
</div>

<!-- Existing lab select (shown only if No) -->
<div class="control-group" ng-if="config.create_new_lab === 'no'">
  <label class="control-label">Select your lab</label>
  <div class="controls">
    <select dku-bs-select="{liveSearch: true}"
            ng-model="config.lab"
            ng-options="c.value as c.label for c in choices.lab">
      <option value="">— select a lab —</option>
    </select>
  </div>
</div>


// Default to "no" on form open
if (!$scope.config.create_new_lab) {
    $scope.config.create_new_lab = "no";
}

// Clear the lab value when switching modes, so stale values don't leak
$scope.$watch("config.create_new_lab", function(newVal, oldVal) {
    if (newVal === oldVal) return;
    $scope.config.lab = null;
    $scope.labNameError = "";
    // Also clear downstream cascades
    $scope.config.owner_id = null;
    $scope.config.consumers = [];
    $scope.config.contributors = [];
    $scope.choices.owner_id = [];
    $scope.choices.consumers = [];
    $scope.choices.contributors = [];
});


$scope.labNameError = "";
var LAB_NAME_RE = /^[A-Za-z0-9_-]{1,64}$/;

$scope.$watch("config.lab", function(newVal) {
    // Only validate in "yes" mode
    if ($scope.config.create_new_lab === "yes") {
        if (!newVal) {
            $scope.labNameError = "";
        } else if (!LAB_NAME_RE.test(newVal)) {
            $scope.labNameError = "Only letters, digits, underscore and dash (max 64 chars)";
        } else {
            $scope.labNameError = "";
        }
    }
});







{ "name": "create_new_lab", "label": "Create new lab?", "type": "STRING", "defaultValue": "no" },
{ "name": "lab",            "label": "Lab",             "type": "STRING", "mandatory": true }






import re

LAB_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

def run(self, progress_callback):
    create_new_lab = self.config.get("create_new_lab", "no")
    lab_name = (self.config.get("lab") or "").strip()

    if not lab_name:
        raise Exception("Lab is required")

    if create_new_lab == "yes":
        # Free-text path: validate format
        if not LAB_NAME_RE.match(lab_name):
            raise Exception(
                f"Invalid lab name '{lab_name}'. "
                "Only letters, digits, underscore and dash (max 64 chars)."
            )
        # Optional: check it doesn't already exist
        existing = {l["id"] for l in list_labs_for_domain(self.config["domain"])}
        if lab_name in existing:
            raise Exception(
                f"Lab '{lab_name}' already exists. "
                "Pick it from the list instead of creating a new one."
            )
    else:
        # Select path: must be in the known list for the domain
        existing = {l["id"] for l in list_labs_for_domain(self.config["domain"])}
        if lab_name not in existing:
            raise Exception(
                f"Selected lab '{lab_name}' does not belong to domain '{self.config['domain']}'"
            )

    # ... rest of project creation
