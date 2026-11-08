<#
.SYNOPSIS
    Read-only export of the data that sitescorecard reads: the Intune managed devices (Microsoft Graph) as devices.csv and the tickets
    of Jira Service Management (Jira Cloud REST API) as tickets.csv.

.DESCRIPTION
    Only read operations: Get-Mg* cmdlets and GET requests. Nothing is created, changed, assigned or deleted, and no credential or token
    is written to disk.

    Devices (devices.csv)
      Microsoft Graph PowerShell SDK (Microsoft.Graph.Authentication, Microsoft.Graph.DeviceManagement, Microsoft.Graph.Users), signed in
      with Connect-MgGraph (interactive) and the read scopes DeviceManagementManagedDevices.Read.All and User.Read.All.
      Get-MgDeviceManagementManagedDevice -All -Property id, deviceName, operatingSystem, complianceState, osVersion, isEncrypted,
      lastSyncDateTime, enrolledDateTime, userPrincipalName. Only Windows and macOS devices are kept unless -AllPlatforms.
      The site comes from the primary user's officeLocation (Get-MgUser -All -Property userPrincipalName, officeLocation) through -SiteMap,
      or from the device name prefix with -SiteFromDeviceName (MAD-L0001 -> MAD).
      PurchaseDate comes from -PurchaseDates (a CSV with DeviceName and PurchaseDate from your asset register); without it the Intune
      enrolledDateTime is used, which is the latest the device can have been bought, so the age is a lower bound.
      Snapshot is the date of the export. With -Append, the rows are added to an existing devices.csv so that the file keeps one snapshot
      per month (the scorecard compares the last snapshot of the month with the one of the previous month).

    Tickets (tickets.csv)
      Jira Cloud REST API v3, enhanced search: GET https://<site>.atlassian.net/rest/api/3/search/jql with jql, fields, maxResults and
      nextPageToken; the loop stops when isLast is true. Basic authentication with your Atlassian account e-mail and an API token, both
      asked with Get-Credential and kept in memory only. The account needs Browse projects on the service project.
      Fields read: key, created, resolutiondate, priority, issuetype and labels, plus the custom fields you name:
        -SiteField          the field that holds the site or office (a select list, for example customfield_10120)
        -SlaField           the JSM SLA field to report (for example "Time to resolution", customfield_10030): SLAMet is No when any
                            completed cycle or the ongoing cycle is breached
        -SatisfactionField  the JSM Satisfaction field (rating 1-5)
      FCR, Reopened and Escalated are not native fields; most teams set them with an automation rule. The script reads them from labels
      (-FcrLabel, -ReopenedLabel, -EscalatedLabel); change the labels to yours or map your own fields after the export.
      The JQL defaults to the tickets created or resolved since the first day of the previous month, plus everything still open.

    Not exported here (see docs/data-format.md): sites.csv (by hand), availability.csv (the outage or problem report of your monitoring
    tool: Zabbix, SolarWinds, PRTG), projects.csv (your tracker), dr_tests.csv (the DR/BCP test register) and settings.json.

.PARAMETER OutputFolder
    Where the CSV files are written (default .\data).

.PARAMETER SiteMap
    Hashtable of officeLocation to site code: @{ 'Madrid - Paseo de la Castellana' = 'MAD'; 'Paris La Défense' = 'PAR' }.

.PARAMETER SiteFromDeviceName
    Take the site code from the device name, up to the first hyphen.

.PARAMETER PurchaseDates
    CSV with DeviceName and PurchaseDate (from the asset register) for the hardware age.

.PARAMETER AllPlatforms
    Keep iOS, Android and other platforms too (default: Windows and macOS only).

.PARAMETER Append
    Add the devices to an existing devices.csv instead of replacing it.

.PARAMETER JiraSite
    The Jira Cloud site, for example https://contoso.atlassian.net. Without it, tickets.csv is not exported.

.PARAMETER Project
    The service project key (for example ITSD).

.PARAMETER Jql
    Your own JQL instead of the default one.

.EXAMPLE
    .\scripts\Export-SiteScorecardData.ps1 -OutputFolder .\data -SiteFromDeviceName -Append `
        -JiraSite https://contoso.atlassian.net -Project ITSD -SiteField customfield_10120 -SlaField customfield_10030 -SatisfactionField customfield_10031

.EXAMPLE
    .\scripts\Export-SiteScorecardData.ps1 -OutputFolder .\data -SiteMap @{ 'Madrid' = 'MAD'; 'Paris' = 'PAR' } -PurchaseDates .\downloads\assets.csv
    Devices only.
#>
[CmdletBinding()]
param(
    [string] $OutputFolder = '.\data',
    [hashtable] $SiteMap = @{},
    [switch] $SiteFromDeviceName,
    [string] $PurchaseDates,
    [switch] $AllPlatforms,
    [switch] $Append,
    [string] $JiraSite,
    [string] $Project,
    [string] $Jql,
    [string] $SiteField,
    [string] $SlaField,
    [string] $SatisfactionField,
    [string] $FcrLabel = 'fcr',
    [string] $ReopenedLabel = 'reopened',
    [string] $EscalatedLabel = 'escalated-central'
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutputFolder | Out-Null

function Format-Date($Value, [switch] $WithTime) {
    if (-not $Value) { return '' }
    $d = ([datetime] $Value).ToUniversalTime()
    if ($WithTime) { return $d.ToString('yyyy-MM-dd HH:mm') }
    return $d.ToString('yyyy-MM-dd')
}

# ------------------------------------------------------------------ devices (Microsoft Graph, read-only)
if (-not (Get-MgContext)) {
    Connect-MgGraph -NoWelcome -Scopes 'DeviceManagementManagedDevices.Read.All', 'User.Read.All'
}
$office = @{}
if (-not $SiteFromDeviceName) {
    foreach ($u in Get-MgUser -All -Property userPrincipalName, officeLocation) {
        if ($u.OfficeLocation) { $office[$u.UserPrincipalName.ToLower()] = $u.OfficeLocation }
    }
}
$bought = @{}
if ($PurchaseDates) {
    foreach ($r in Import-Csv $PurchaseDates) { $bought[$r.DeviceName.ToUpper()] = $r.PurchaseDate }
}
$snapshot = (Get-Date).ToString('yyyy-MM-dd')
$props = 'id', 'deviceName', 'operatingSystem', 'complianceState', 'osVersion', 'isEncrypted', 'lastSyncDateTime', 'enrolledDateTime', 'userPrincipalName'
$devices = foreach ($d in Get-MgDeviceManagementManagedDevice -All -Property $props) {
    if (-not $AllPlatforms -and $d.OperatingSystem -notin @('Windows', 'macOS')) { continue }
    $site = ''
    if ($SiteFromDeviceName) { $site = ($d.DeviceName -split '-')[0] }
    elseif ($d.UserPrincipalName -and $office.ContainsKey($d.UserPrincipalName.ToLower())) {
        $loc = $office[$d.UserPrincipalName.ToLower()]
        $site = if ($SiteMap.ContainsKey($loc)) { $SiteMap[$loc] } else { $loc }
    }
    $purchase = if ($bought.ContainsKey($d.DeviceName.ToUpper())) { $bought[$d.DeviceName.ToUpper()] } else { Format-Date $d.EnrolledDateTime }
    [pscustomobject]@{
        Snapshot         = $snapshot
        DeviceName       = $d.DeviceName
        Site             = $site
        ComplianceState  = [string] $d.ComplianceState
        OSVersion        = $d.OsVersion
        IsEncrypted      = $d.IsEncrypted
        LastSyncDateTime = Format-Date $d.LastSyncDateTime
        PurchaseDate     = $purchase
    }
}
$devPath = Join-Path $OutputFolder 'devices.csv'
if ($Append -and (Test-Path $devPath)) {
    $devices | Export-Csv -Path $devPath -NoTypeInformation -Encoding utf8 -Append
} else {
    $devices | Export-Csv -Path $devPath -NoTypeInformation -Encoding utf8
}
Write-Host ("{0,7} devices -> {1} (snapshot {2})" -f @($devices).Count, $devPath, $snapshot)

# ------------------------------------------------------------------ tickets (Jira Cloud REST API, GET only)
if ($JiraSite) {
    if (-not $Project -and -not $Jql) { throw 'Give -Project or -Jql for the tickets.' }
    $cred = Get-Credential -Message 'Atlassian account e-mail and API token (kept in memory only)'
    $pair = '{0}:{1}' -f $cred.UserName, $cred.GetNetworkCredential().Password
    $headers = @{ Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair)); Accept = 'application/json' }
    if (-not $Jql) {
        $since = (Get-Date -Day 1).AddMonths(-1).ToString('yyyy-MM-dd')
        $Jql = "project = $Project AND (created >= '$since' OR resolved >= '$since' OR resolution = Unresolved) ORDER BY created ASC"
    }
    $fields = @('key', 'created', 'resolutiondate', 'priority', 'issuetype', 'labels') + @($SiteField, $SlaField, $SatisfactionField | Where-Object { $_ })
    $base = $JiraSite.TrimEnd('/') + '/rest/api/3/search/jql'
    $token = $null
    $tickets = New-Object System.Collections.Generic.List[object]
    do {
        $query = 'jql=' + [uri]::EscapeDataString($Jql) + '&maxResults=100&fields=' + [uri]::EscapeDataString($fields -join ',')
        if ($token) { $query += '&nextPageToken=' + [uri]::EscapeDataString($token) }
        $page = Invoke-RestMethod -Method Get -Uri "$base`?$query" -Headers $headers
        foreach ($i in $page.issues) {
            $f = $i.fields
            $labels = @($f.labels)
            $sla = ''
            if ($SlaField -and $f.$SlaField -and $f.resolutiondate) {
                $v = $f.$SlaField
                $breached = @($v.completedCycles | Where-Object { $_.breached }).Count -gt 0 -or ($v.ongoingCycle -and $v.ongoingCycle.breached)
                $sla = if ($breached) { 'No' } else { 'Yes' }
            }
            $siteValue = if ($SiteField -and $f.$SiteField) { if ($f.$SiteField.value) { $f.$SiteField.value } else { [string] $f.$SiteField } } else { '' }
            $rating = if ($SatisfactionField -and $f.$SatisfactionField) { $f.$SatisfactionField.rating } else { '' }
            $tickets.Add([pscustomobject]@{
                Key          = $i.key
                Site         = $siteValue
                Created      = Format-Date $f.created -WithTime
                Resolved     = Format-Date $f.resolutiondate -WithTime
                Priority     = $f.priority.name
                Type         = $f.issuetype.name
                SLAMet       = $sla
                FCR          = if ($f.resolutiondate) { if ($labels -contains $FcrLabel) { 'Yes' } else { 'No' } } else { '' }
                Reopened     = if ($labels -contains $ReopenedLabel) { 1 } else { 0 }
                Escalated    = if ($labels -contains $EscalatedLabel) { 'Yes' } else { 'No' }
                Satisfaction = $rating
            })
        }
        $token = $page.nextPageToken
    } while (-not $page.isLast -and $token)
    $tkPath = Join-Path $OutputFolder 'tickets.csv'
    $tickets | Export-Csv -Path $tkPath -NoTypeInformation -Encoding utf8
    Write-Host ("{0,7} tickets -> {1}" -f $tickets.Count, $tkPath)
}

Write-Host 'Add sites.csv, availability.csv (from your monitoring tool), projects.csv, dr_tests.csv and settings.json, then run:'
Write-Host '  python -m sitescorecard review data/'
