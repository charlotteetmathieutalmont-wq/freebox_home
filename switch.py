"""Freebox switch platform for WiFi, call alerts, and home automation.

Controls WiFi state and home automation device switches.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from freebox_api.exceptions import InsufficientPermissionsError

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    TEMP_REFRESH_DURATION,
    TEMP_REFRESH_INTERVAL,
    CONF_TEMP_REFRESH_INTERVAL,
    DEFAULT_TEMP_REFRESH_INTERVAL,
    CONF_TEMP_REFRESH_DURATION,
    DEFAULT_TEMP_REFRESH_DURATION,
)
from .router import FreeboxRouter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """ Set up the Freebox switch entities.
    
    Discovers all switches: the WiFi toggle plus any smart home devices
    (like smart plugs) that have switch-type endpoints.
    
    HOW IT WORKS:
    1. Always add a WiFi switch (to control router's WiFi)
    2. Loop through all home automation devices
    3. Find any that have boolean "slot" endpoints (these are switches)
    4. Skip shutters (they're covers, not switches)
        Args:
            hass: Home Assistant instance coordinating the integration
        Args:
            entry: Config entry providing router runtime data
        Args:
            async_add_entities: Callback used to register entities with HA
        Returns:
            None
        See Also:
            FreeboxHomeNodeSwitch
        See Also:
            FreeboxWifiSwitch
    """
    router: FreeboxRouter = entry.runtime_data

    entities = []

    # Always add the WiFi control switch
    entities.append(FreeboxWifiSwitch(router))

    _LOGGER.info(
        "%s - %s - %s home node(s)", router.name, router.mac, len(router.home_nodes)
    )

    # Find all home automation switches
    for home_node in router.home_nodes.values():
        # Skip shutters (they're handled by cover.py)
        if home_node["category"] != "shutter":
            # Look for switch-type endpoints (boolean slots)
            for endpoint in home_node.get("show_endpoints"):
                if endpoint["ep_type"] == "slot" and endpoint["value_type"] == "bool":
                    # Found a switch! Add it to our list
                    entities.append(
                        FreeboxHomeNodeSwitch(
                            router,
                            home_node,
                            endpoint,
                            endpoint["name"],
                        )
                    )

    async_add_entities(entities, True)


class FreeboxSwitch(SwitchEntity):
    """ Representation of a Freebox switch.
    
    Base class for Freebox switch entities with common functionality.
    """

    _attr_should_poll = False

    def __init__(
        self,
        router: FreeboxRouter,
        endpoint_name: str,
        unik: Any,
    ) -> None:
        """ Initialize a Freebox switch.
        Args:
            router: FreeboxRouter instance managing API access
        Args:
            endpoint_name: Name of the endpoint represented by this switch
        Args:
            unik: Unique identifier component for the switch
        Returns:
            None
        """
        self.entity_description = SwitchEntityDescription(
            key="switch", name=endpoint_name
        )
        self._router = router
        self._unik = unik
        self._attr_unique_id = f"{router.mac} {endpoint_name} {unik}"

    @callback
    def async_update_state(self) -> None:
        """ Update the Freebox switch state.
        
        Placeholder for subclasses to populate the on/off state from router data.
        Returns:
            None
        """
        # state = self._router.sensors[self.entity_description.key]
        # self._attr_is_on = state

    @property
    def device_info(self) -> DeviceInfo:
        """ Return the device information.
        Returns:
            DeviceInfo object containing device details
        """
        return self._router.device_info

    @callback
    def async_on_demand_update(self) -> None:
        """ Update state on demand.
        
        Called when dispatcher signals a state change. Refreshes the state and
        pushes it to Home Assistant.
        Returns:
            None
        """
        self.async_update_state()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register state update callback.
        
        Called when entity is added to Home Assistant.
        Returns:
            None
        """
        self.async_update_state()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self._router.signal_sensor_update,
                self.async_on_demand_update,
            )
        )


class FreeboxHomeNodeSwitch(FreeboxSwitch):
    """ Representation of a Freebox Home node switch.
    
    Switch entity for controlling Freebox home automation nodes.
    """

    def __init__(
        self,
        router: FreeboxRouter,
        home_node: dict[str, Any],
        endpoint: dict[str, Any],
        description: SwitchEntityDescription,
    ) -> None:
        """ Initialize a Freebox Home node switch.
        Args:
            router: FreeboxRouter instance managing API access
        Args:
            home_node: Mapping containing home node information
        Args:
            endpoint: Mapping containing endpoint information
        Args:
            description: Switch entity description metadata
        Returns:
            None
        """
        super().__init__(router, description, f"{home_node['id']} {endpoint['id']}")
        self._home_node = home_node
        self._endpoint = endpoint
        self._attr_name = f"{home_node['label']} {endpoint['name']}"
        self._unique_id = f"{self._router.mac} {endpoint['name']} {self._home_node['id']} {endpoint['id']}"
        self._enabled = None
        self._get_endpoint_id = None

        # Discover for get endpoint
        for endpoint_candidate in home_node.get("show_endpoints"):
            if (
                endpoint_candidate["name"] == endpoint["name"]
                and endpoint_candidate["ep_type"] == "signal"
            ):
                self._get_endpoint_id = endpoint_candidate["id"]
                break

    @property
    def device_info(self) -> DeviceInfo:
        """ Return the device information.
        Returns:
            DeviceInfo object containing device details including firmware version.
        """
        fw_version = None
        if "props" in self._home_node:
            props = self._home_node["props"]
            if "FwVersion" in props:
                fw_version = props["FwVersion"]

        return DeviceInfo(
            identifiers={(DOMAIN, self._home_node["id"])},
            model=f'{self._home_node["category"]}',
            name=f"{self._home_node['label']}",
            sw_version=str(fw_version),
            """"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfDataRate, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.util.dt as dt_util


from .const import (
    CALL_SENSORS,
    CONNECTION_SENSORS,
    DISK_PARTITION_SENSORS,
    DOMAIN,
    HOME_NODES_ALARM_REMOTE_KEY,
    HOME_NODES_SENSORS,
)
from .router import FreeboxRouter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """ Set up Freebox sensor entities from a config entry.
    
    Creates and registers various sensor entities including temperature sensors,
    connection sensors, call sensors, disk sensors, and home node sensors.
        Args:
            hass: Home Assistant instance coordinating the integration
        Args:
            entry: Config entry providing router runtime data
        Args:
            async_add_entities: Callback used to register entities with HA
        Returns:
            None
        See Also:
            FreeboxSensor
    """
    router: FreeboxRouter = entry.runtime_data
    entities = []

    _LOGGER.debug(
        "%s - %s - %s temperature sensors",
        router.name,
        router.mac,
        len(router.sensors_temperature),
    )
    entities = [
        FreeboxSensor(
            router,
            SensorEntityDescription(
                key=sensor_name,
                name=f"Freebox {sensor_name}",
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                device_class=SensorDeviceClass.TEMPERATURE,
            ),
            router.mac,
        )
        for sensor_name in router.sensors_temperature
    ]

    entities.extend(
        [
            FreeboxSensor(router, description, router.mac)
            for description in CONNECTION_SENSORS
        ]
    )
    entities.extend(
        [FreeboxCallSensor(router, description) for description in CALL_SENSORS]
    )

    _LOGGER.info("%s - %s - %s disk(s)", router.name, router.mac, len(router.disks))
    entities.extend(
        FreeboxDiskSensor(router, disk, partition, description)
        for disk in router.disks.values()
        for partition in disk["partitions"]
        for description in DISK_PARTITION_SENSORS
    )

    _LOGGER.info(
        "%s - %s - %s home node(s)", router.name, router.mac, len(router.home_nodes)
    )

    for home_node in router.home_nodes.values():
        for endpoint in home_node.get("show_endpoints"):
            if (
                endpoint["ep_type"] == "signal"
                and endpoint["name"] in HOME_NODES_SENSORS.keys()
            ):
                entities.append(
                    FreeboxHomeNodeSensor(
                        router,
                        home_node,
                        endpoint,
                        HOME_NODES_SENSORS[endpoint["name"]],
                    )
                )

    async_add_entities(entities, True)


class FreeboxSensor(SensorEntity):
    """ Representation of a Freebox sensor.
    
    Base class for all Freebox sensor entities. Handles state updates
    via dispatcher signals rather than polling.
    """

    _attr_should_poll = False

    def __init__(
        self, router: FreeboxRouter, description: SensorEntityDescription, unik: Any
    ) -> None:
        """ Initialize a Freebox sensor.
        Args:
            router: FreeboxRouter instance managing the connection
        Args:
            description: Entity description containing sensor metadata
        Args:
            unik: Unique identifier for this sensor instance
        Returns:
            None
        """
        self.entity_description = description
        self._router = router
        self._unik = unik
        self._attr_unique_id = f"{router.mac} {description.name} {unik}"

    @callback
    def async_update_state(self) -> None:
        """ Update the Freebox sensor state.

        Retrieves the current sensor value from the router and converts
        data rate values from bytes/s to kilobytes/s when appropriate.
        Returns:
            None
        """
        state = self._router.sensors[self.entity_description.key]
        if self.native_unit_of_measurement == UnitOfDataRate.KILOBYTES_PER_SECOND:
            self._attr_native_value = round(state / 1000, 2)
        else:
            self._attr_native_value = state

    @property
    def device_info(self) -> DeviceInfo:
        """ Return the device information.
        Returns:
            DeviceInfo object containing router device information
        """
        return self._router.device_info

    @callback
    def async_on_demand_update(self) -> None:
        """ Update state on demand.

        Called when a dispatcher signal is received. Updates the sensor
        state and writes it to Home Assistant.
        Returns:
            None
        """
        self.async_update_state()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register state update callback.
        
        Called when the entity is added to Home Assistant. Performs initial
        state update and registers for dispatcher signals.
        Returns:
            None
        """
        self.async_update_state()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self._router.signal_sensor_update,
                self.async_on_demand_update,
            )
        )


class FreeboxCallSensor(FreeboxSensor):
    """ Representation of a Freebox call sensor.
    
    Tracks phone call events (missed, received, outgoing) and provides
    call history as extra state attributes.
    """

    def __init__(
        self, router: FreeboxRouter, description: SensorEntityDescription
    ) -> None:
        """ Initialize a Freebox call sensor.
        Args:
            router: FreeboxRouter instance managing the connection
        Args:
            description: Entity description containing sensor metadata
        Returns:
            None
        """
        super().__init__(router, description, router.mac)
        self._call_list_for_type: list[dict[str, Any]] = []

    @callback
    def async_update_state(self) -> None:
        """ Update the Freebox call sensor state.

        Filters the call list for new calls matching this sensor's type
        and updates the count accordingly.
        Returns:
            None
        """
        self._call_list_for_type = []
        if self._router.call_list:
            for call in self._router.call_list:
                if not call["new"]:
                    continue
                if self.entity_description.key == call["type"]:
                    self._call_list_for_type.append(call)

        self._attr_native_value = len(self._call_list_for_type)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """ Return device specific state attributes.
        
        Provides call history with timestamps as ISO format strings and
        caller names as values.
        Returns:
            Dictionary mapping ISO timestamp strings to caller names
        """
        return {
            dt_util.utc_from_timestamp(call["datetime"]).isoformat(): call["name"]
            for call in self._call_list_for_type
        }


class FreeboxDiskSensor(FreeboxSensor):
    """ Representation of a Freebox disk sensor.
    
    Monitors disk partition usage and reports free space percentage.
    """

    def __init__(
        self,
        router: FreeboxRouter,
        disk: dict[str, Any],
        partition: dict[str, Any],
        description: SensorEntityDescription,
    ) -> None:
        """ Initialize a Freebox disk sensor.
        Args:
            router: FreeboxRouter instance managing the connection
        Args:
            disk: Mapping containing disk metadata
        Args:
            partition: Mapping containing partition information
        Args:
            description: Entity description containing sensor metadata
        Returns:
            None
        """
        super().__init__(router, description, f"{disk['id']} {partition['id']}")
        self._disk = disk
        self._partition = partition
        self._attr_name = f"{partition['label']} {description.name}"
        self._unique_id = f"{self._router.mac} {description.key} {self._disk['id']} {self._partition['id']}"

    @property
    def device_info(self) -> DeviceInfo:
        """ Return the device information.

        Provides device information specific to the disk, including model,
        firmware version, and connection to the router.
        Returns:
            DeviceInfo object containing disk device information
        """
        return DeviceInfo(
            identifiers={(DOMAIN, self._disk["id"])},
            model=self._disk["model"],
            name=f"Disk {self._disk['id']}",
            sw_version=str(self._disk["firmware"]),
            via_device_id=router.device_id,
            manufacturer="Freebox SAS",
        )

    @callback
    def async_update_state(self) -> None:
        """ Update the Freebox disk sensor state.

        Calculates the free space percentage for the partition by
        comparing free bytes to total bytes.
        Returns:
            None
        """
        value = None
        current_disk = self._router.disks.get(self._disk.get("id"))
        for partition in current_disk["partitions"]:
            if self._partition["id"] == partition["id"]:
                """In case of a RAID configuration, partition["total_bytes"] = 0 for a disk which is member of the RAID array, free disk space is O and we avoid ZeroDivisionError"""
                value = round(
                    (
                      partition["free_bytes"] * 100 / partition["total_bytes"]
                      if partition["total_bytes"] != 0
                      else 0
                    ), 2
                )
        self._attr_native_value = value


class FreeboxHomeNodeSensor(FreeboxSensor):
    """ Representation of a Freebox Home node sensor.
    
    Monitors Freebox Home automation nodes and their endpoints,
    such as alarm remotes and various sensors.
    """

    def __init__(
        self,
        router: FreeboxRouter,
        home_node: dict[str, Any],
        endpoint: dict[str, Any],
        description: SensorEntityDescription,
    ) -> None:
        """ Initialize a Freebox Home node sensor.
        Args:
            router: FreeboxRouter instance managing the connection
        Args:
            home_node: Mapping containing home node information
        Args:
            endpoint: Mapping containing endpoint information
        Args:
            description: Entity description containing sensor metadata
        Returns:
            None
        """
        super().__init__(router, description, f"{home_node['id']} {endpoint['id']}")
        self._home_node = home_node
        self._endpoint = endpoint
        self._attr_name = f"{home_node['label']} {description.name}"
        self._unique_id = f"{self._router.mac} {description.key} {self._home_node['id']} {endpoint['id']}"

    @property
    def device_info(self) -> DeviceInfo:
        """ Return the device information.

        Provides device information specific to the home node, including
        category, label, firmware version if available, and connection to the router.
        Returns:
            DeviceInfo object containing home node device information
        """
        fw_version = None
        if "props" in self._home_node:
            props = self._home_node["props"]
            if "FwVersion" in props:
                fw_version = props["FwVersion"]

        return DeviceInfo(
            identifiers={(DOMAIN, self._home_node["id"])},
            model=f'{self._home_node["category"]}',
            name=f"{self._home_node['label']}",
            sw_version=str(fw_version),
            via_device_id=router.device_id,
            manufacturer="Freebox SAS",
        )

    @callback
    def async_update_state(self) -> None:
        """ Update the Freebox Home node sensor state.

        Retrieves the current value from the home node endpoint. For button
        push endpoints, translates the button value to a human-readable key name.
        Returns:
            None
        """
        value = None

        current_home_node = self._router.home_nodes.get(self._home_node.get("id"))
        if current_home_node.get("show_endpoints"):
            for end_point in current_home_node["show_endpoints"]:
                if self._endpoint["id"] == end_point["id"]:
                    if self._endpoint["name"] == "pushed":
                        if len(end_point.get("history")) > 0:
                            # Get the latest button pushed as pool mode is a mess
                            value = end_point.get("history")[-1].get("value")
                            value = HOME_NODES_ALARM_REMOTE_KEY[int(value) - 1]
                    else:
                        value = end_point["value"]
                    break

        self._attr_native_value = value
,
            manufacturer="Freebox SAS",
        )

    @property
    def is_on(self) -> bool:
        """ Return true if device is on.
        Returns:
            True if the switch is on, False otherwise.
        """
        return self._enabled

    @callback
    def async_update_state(self) -> None:
        """ Update the Freebox Home node switch state.
        
        Reads the latest endpoint value from the router snapshot and synchronizes
        the entity attributes, ensuring Home Assistant reflects the real device state.
        Returns:
            None
        """
        current_home_node = self._router.home_nodes.get(self._home_node.get("id"))
        if current_home_node.get("show_endpoints"):
            for end_point in current_home_node["show_endpoints"]:
                if self._get_endpoint_id == end_point["id"]:
                    self._enabled = end_point["value"]
                    break
        self._attr_is_on = self._enabled

    async def get_state(self) -> bool | None:
        """ Get the current switch state from the API.
        
        Fetches the complete node data (more efficient) and extracts the switch state.
        Unlike covers, switches are simple: True = on, False = off.
        Returns:
            Boolean state value (True if on, False if off)
        """
        try:
            # Get complete node data (all endpoints) in one API call
            node_data = await self._router.get_node_data(self._home_node["id"])
            if node_data and "show_endpoints" in node_data:
                # Find the state endpoint in the node data
                for endpoint in node_data["show_endpoints"]:
                    if endpoint["id"] == self._get_endpoint_id:
                        self._enabled = endpoint["value"]
                        self._attr_is_on = self._enabled
                        break
        except InsufficientPermissionsError as err:
            _LOGGER.warning(
                "Home Assistant does not have permissions to read Freebox settings: %s", err
            )
        except Exception as err:
            _LOGGER.error(
                "Unexpected error getting switch state for %s: %s",
                self._attr_name,
                err,
            )
        return self._enabled

    async def _start_temp_refresh(self) -> None:
        """
        Start fast polling after state changes.
        
        WHY FOR SWITCHES?
        Even though switches are simpler than covers (just on/off),
        the physical device might take a moment to respond.
        We poll the Freebox API at a configurable interval for 120 seconds to quickly show the real state.
        """
        # Get the configured refresh interval and duration
        refresh_interval = self._router.config_entry.options.get(
            CONF_TEMP_REFRESH_INTERVAL, DEFAULT_TEMP_REFRESH_INTERVAL
        )
        refresh_duration = self._router.config_entry.options.get(
            CONF_TEMP_REFRESH_DURATION, DEFAULT_TEMP_REFRESH_DURATION
        )
        
        # Create refresh callback
        async def _refresh() -> None:
            await self.get_state()
            self.async_write_ha_state()
        
        # Use global timer system
        self._router.start_entity_refresh_timer(
            entity_id=self.entity_id,
            refresh_callback=_refresh,
            interval_seconds=refresh_interval,
            duration_seconds=refresh_duration,
        )

    async def async_will_remove_from_hass(self) -> None:
        """
        Clean up when switch is removed from Home Assistant.
        
        Stop the fast polling timer if it's running.
        """
        self._router.stop_entity_refresh_timer(self.entity_id)

    async def _async_set_state(self, enabled: bool) -> None:
        """ Turn the switch on or off.
        
        Sends the command to the Freebox to change the switch state.
        Then starts fast polling to quickly reflect the actual state change.
        Args:
            enabled: True to enable, False to disable the endpoint
        Returns:
            None
        """
        # Prepare the command payload
        value_enabled = {"value": enabled}
        try:
            # Send the command to the Freebox
            await self._router._api.home.set_home_endpoint_value(
                self._home_node["id"], self._endpoint["id"], value_enabled
            )
            # Optimistically update our local state
            self._enabled = enabled
            # Start fast polling to confirm the change
            await self._start_temp_refresh()
        except InsufficientPermissionsError as err:
            _LOGGER.warning(
                "Home Assistant does not have permissions to modify the Freebox settings. Please refer to documentation: %s",
                err,
            )
        except asyncio.TimeoutError as err:
            _LOGGER.error(
                "Timeout setting home endpoint value for %s (id=%s, endpoint_id=%s): %s",
                self._attr_name,
                self._home_node["id"],
                self._endpoint["id"],
                err,
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """ Turn the switch on.
        Args:
            kwargs: Additional keyword arguments (unused)
        Returns:
            None
        """
        # Cancel any existing refresh timer to start fresh
        self._router.stop_entity_refresh_timer(self.entity_id)
        
        await self._async_set_state(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """ Turn the switch off.
        Args:
            kwargs: Additional keyword arguments (unused)
        Returns:
            None
        """
        # Cancel any existing refresh timer to start fresh
        self._router.stop_entity_refresh_timer(self.entity_id)
        
        await self._async_set_state(False)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update the entity state.
        
        Note: This is a lifecycle method and should not return a value.
        """
        # async_update should just update internal state, not return


class FreeboxWifiSwitch(SwitchEntity):
    """ Representation of a Freebox WiFi switch.

    Switch entity for controlling the Freebox router WiFi functionality.
    """

    def __init__(self, router: FreeboxRouter) -> None:
        """ Initialize the WiFi switch entity.
        Args:
            router: FreeboxRouter instance managing API access
        Returns:
            None
        """
        self._name = "Freebox WiFi"
        self._state: bool | None = None
        self._router = router
        self._unique_id = f"{self._router.mac} {self._name}"

    @property
    def unique_id(self) -> str:
        """ Return a unique ID.
        Returns:
            Unique identifier string for the entity.
        """
        return self._unique_id

    @property
    def name(self) -> str:
        """ Return the name of the switch.
        Returns:
            The switch entity name.
        """
        return self._name

    @property
    def is_on(self) -> bool | None:
        """ Return true if device is on.
        Returns:
            True if WiFi is on, False if off, None if unknown.
        """
        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        """ Return the device information.
        Returns:
            DeviceInfo object containing device details.
        """
        return self._router.device_info

    async def _async_set_state(self, enabled: bool) -> None:
        """ Turn the WiFi switch on or off.
        Args:
            enabled: True to enable WiFi, False to disable
        Returns:
            None
        """
        wifi_config = {"enabled": enabled}
        try:
            await self._router.wifi.set_global_config(wifi_config)
        except InsufficientPermissionsError as err:
            _LOGGER.warning(
                "Home Assistant does not have permissions to modify WiFi settings: %s", err
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """ Turn the WiFi switch on.
        Args:
            kwargs: Additional keyword arguments (unused)
        Returns:
            None
        """
        # Cancel any existing refresh timer to start fresh
        self._router.stop_entity_refresh_timer(self.entity_id)
        
        await self._async_set_state(True)
        # Get immediate state confirmation
        await self.async_update()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """ Turn the WiFi switch off.
        Args:
            kwargs: Additional keyword arguments (unused)
        Returns:
            None
        """
        # Cancel any existing refresh timer to start fresh
        self._router.stop_entity_refresh_timer(self.entity_id)
        
        await self._async_set_state(False)
        # Get immediate state confirmation
        await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Get the state and update it.
        
        Fetches the current WiFi state from the router.
        Returns:
            None
        """
        datas = await self._router.wifi.get_global_config()
        active = datas["enabled"]
        self._state = bool(active)
