var app = angular.module('myplugin.projectForm', []);

app.controller('ProjectFormController', function($scope, $timeout) {

    // -------------------------------------------------------------------
    // State initialization
    // -------------------------------------------------------------------
    $scope.choices = {
        domain: [],
        lab: [],
        owner_id: [],
        consumers: [],
        contributors: [],
        existing_project: []
    };

    $scope.nameCheck = { ok: null, message: "" };
    $scope.labNameError = "";

    var LAB_NAME_RE = /^[A-Za-z0-9_-]{1,64}$/;

    // Defaults
    if (!$scope.config.create_new_lab)     $scope.config.create_new_lab = "no";
    if (!$scope.config.create_new_project) $scope.config.create_new_project = "no";
    if (!$scope.config.consumers)          $scope.config.consumers = [];
    if (!$scope.config.contributors)       $scope.config.contributors = [];

    // -------------------------------------------------------------------
    // Generic choices loader
    // -------------------------------------------------------------------
    function loadChoices(paramName) {
        $scope.callPythonDo({ parameterName: paramName }).then(
            function(data) {
                $scope.choices[paramName] = (data && data.choices) || [];
            },
            function(err) {
                console.error("Failed to load " + paramName, err);
                $scope.choices[paramName] = [];
            }
        );
    }

    // Initial load: only domain. Everything else cascades.
    loadChoices("domain");

    // -------------------------------------------------------------------
    // Cascade: domain -> lab list
    // -------------------------------------------------------------------
    $scope.$watch("config.domain", function(newVal, oldVal) {
        if (newVal === oldVal) return;

        // Clear everything downstream
        $scope.config.lab = null;
        $scope.config.owner_id = null;
        $scope.config.consumers = [];
        $scope.config.contributors = [];
        $scope.config.existing_project_key = null;
        $scope.choices.lab = [];
        $scope.choices.owner_id = [];
        $scope.choices.consumers = [];
        $scope.choices.contributors = [];
        $scope.choices.existing_project = [];
        $scope.labNameError = "";

        if (newVal && $scope.config.create_new_lab === "no") {
            loadChoices("lab");
        }
    });

    // -------------------------------------------------------------------
    // Toggle: create_new_lab yes/no
    // -------------------------------------------------------------------
    $scope.$watch("config.create_new_lab", function(newVal, oldVal) {
        if (newVal === oldVal) return;

        // Reset the lab value whenever the mode switches
        $scope.config.lab = null;
        $scope.labNameError = "";

        // Clear downstream cascades
        $scope.config.owner_id = null;
        $scope.config.consumers = [];
        $scope.config.contributors = [];
        $scope.config.existing_project_key = null;
        $scope.choices.owner_id = [];
        $scope.choices.consumers = [];
        $scope.choices.contributors = [];
        $scope.choices.existing_project = [];

        if (newVal === "yes") {
            // New lab => must create new project
            $scope.config.create_new_project = "yes";
        } else {
            // Switching to "pick existing lab": load the lab list if domain is set
            if ($scope.config.domain) {
                loadChoices("lab");
            }
        }
    });

    // -------------------------------------------------------------------
    // Lab name validation (only in "yes" mode) + cascade on any lab change
    // -------------------------------------------------------------------
    $scope.$watch("config.lab", function(newVal, oldVal) {
        if (newVal === oldVal) return;

        // Validate the free-text name when creating a new lab
        if ($scope.config.create_new_lab === "yes") {
            if (!newVal) {
                $scope.labNameError = "";
            } else if (!LAB_NAME_RE.test(newVal)) {
                $scope.labNameError = "Only letters, digits, underscore and dash (max 64 chars)";
            } else {
                $scope.labNameError = "";
            }
        } else {
            $scope.labNameError = "";
        }

        // Clear downstream selections regardless of mode
        $scope.config.owner_id = null;
        $scope.config.consumers = [];
        $scope.config.contributors = [];
        $scope.config.existing_project_key = null;
        $scope.choices.owner_id = [];
        $scope.choices.consumers = [];
        $scope.choices.contributors = [];
        $scope.choices.existing_project = [];

        // Reload downstream lists only if lab value is usable
        if (newVal && !$scope.labNameError) {
            loadChoices("owner_id");
            loadChoices("consumers");
            loadChoices("contributors");
            if ($scope.config.create_new_project === "no") {
                loadChoices("existing_project");
            }
        }
    });

    // -------------------------------------------------------------------
    // Toggle: create_new_project yes/no
    // -------------------------------------------------------------------
    $scope.$watch("config.create_new_project", function(newVal, oldVal) {
        if (newVal === oldVal) return;

        if (newVal === "yes") {
            // Clear the existing-project selection
            $scope.config.existing_project_key = null;
            $scope.choices.existing_project = [];
        } else {
            // Clear the new-project name + its validation state
            $scope.config.project_name = null;
            $scope.nameCheck = { ok: null, message: "" };
            // Load projects for the current lab if available
            if ($scope.config.lab && !$scope.labNameError) {
                loadChoices("existing_project");
            }
        }
    });

    // -------------------------------------------------------------------
    // Project name collision check (only in "create new project" mode)
    // -------------------------------------------------------------------
    var nameCheckPromise = null;

    $scope.onNameChange = function() {
        if (nameCheckPromise) $timeout.cancel(nameCheckPromise);
        $scope.nameCheck = { ok: null, message: "Checking..." };

        nameCheckPromise = $timeout(function() {
            $scope.callPythonDo({ parameterName: "__check_name" }).then(
                function(data) {
                    $scope.nameCheck = {
                        ok: data.ok,
                        message: data.message
                    };
                },
                function(err) {
                    console.error("Name check failed:", err);
                    $scope.nameCheck = { ok: false, message: "Check failed" };
                }
            );
        }, 300);
    };

});
