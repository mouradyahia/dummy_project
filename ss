<div class="control-group">
  <label class="control-label">Lab</label>
  <div class="controls" style="position: relative;">
    <input type="text"
           ng-model="config.lab"
           ng-focus="labDropdownOpen = true"
           ng-change="onLabInputChange()"
           ng-blur="closeLabDropdownSoon()"
           class="form-control"
           autocomplete="off"
           placeholder="Pick a lab or type a new one..." />

    <ul ng-if="labDropdownOpen && filteredLabs.length"
        style="position: absolute; top: 100%; left: 0; right: 0;
               background: white; border: 1px solid #ccc;
               max-height: 200px; overflow-y: auto; z-index: 1000;
               list-style: none; margin: 0; padding: 0;
               box-shadow: 0 2px 6px rgba(0,0,0,0.15);">
      <li ng-repeat="c in filteredLabs"
          ng-mousedown="selectLab(c)"
          style="padding: 6px 12px; cursor: pointer;"
          ng-mouseenter="hoverLab = c.value"
          ng-mouseleave="hoverLab = null"
          ng-style="{background: hoverLab === c.value ? '#f0f0f0' : 'white'}">
        {{c.label}}
      </li>
    </ul>
  </div>
</div>
