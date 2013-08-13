# Software Management Providers
#
# Copyright (C) 2012-2013 Red Hat, Inc.  All rights reserved.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
#
# Authors: Jan Safranek <jsafrane@redhat.com>
#

"""
LVM management functions.
"""

from lmi.scripts.common.errors import LmiFailed
from lmi.scripts.common import get_logger
LOG = get_logger(__name__)
from lmi.scripts.storage import common
from lmi.shell import LMIInstance
import pywbem

def str2vg(c, vg):
    """
    Convert string with name of volume group to LMIInstance of the
    LMI_VGStoragePool.

    If LMIInstance is provided, nothing is done and the instance is just
    returned. If string is provided, appropriate LMIInstance is looked up and
    returned.

    This functions throws an error when the device cannot be found.

    :type vg: LMIInstance/LMI_VGStoragePool or string
    :param vg: VG to retrieve.
    :rtype: LMIInstance/LMI_VGStoragePool

    """
    if isinstance(vg, LMIInstance):
        return vg
    if not isinstance(vg, str):
        raise TypeError("string or LMIInstance expected")
    query = 'SELECT * FROM LMI_VGStoragePool WHERE ElementName="%(vg)s"' \
            % {'vg': common.escape_cql(vg)}
    vgs = c.root.cimv2.wql(query)
    if not vgs:
        raise LmiFailed("Volume Group '%s' not found" % (vg,))
    if len(vgs) > 1:
        raise LmiFailed("Too many volume groups with name '%s' found" % (vg,))

    LOG().debug("String %s translated to Volume Group '%s'",
            vg, vgs[0].InstanceID)
    return vgs[0]


def get_lvs(c, vgs=None):
    """
    Retrieve list of all logical volumes allocated from given volume groups.

    If no volume groups are provided, all logical volumes on the system
    are returned.

    :type vgs: list of LMIInstance/LMI_VGStoragePool or list of strings
    :param vgs: Volume Groups to examine.
    :rtype: list of LMIInstance/LMI_LVStorageExtent.
    """
    if vgs:
        for vg in vgs:
            LOG().debug("Getting LVs on %s", vg.ElementName)
            for lv in get_lvs_on_vg(vg):
                yield lv
    else:
        # No vgs supplied, list all LVs
        for lv in c.root.cimv2.LMI_LVStorageExtent.instances():
            yield lv

def create_lv(c, vg, name, size):
    """
    Create new Logical Volume on given Volume Group.

    :type vg: LMIInstance/LMI_VGStoragePool or string
    :param vg: Volume Group to allocate the volume from.
    :type name: string
    :param name: Name of the logical volume.
    :type size: int
    :param size: Size of the logical volume in bytes.
    :rtype: LMIInstance/LMI_LVStorageExtent
    """
    vg = str2vg(c, vg)
    service = c.root.cimv2.LMI_StorageConfigurationService.first_instance()
    (ret, outparams, err) = service.SyncCreateOrModifyLV(
            ElementName=name,
            Size=size,
            InPool=vg)
    if ret != 0:
        raise LmiFailed("Cannot create the logical volume: %s."
                % (service.CreateOrModifyLV.CreateOrModifyLVValues.value_name(ret),))
    return outparams['TheElement']


def delete_lv(c, lv):
    """
    Destroy given Logical Volume.

    :type lv: LMIInstance/LMI_LVStorageExtent or string
    :param lv: Logical Volume to destroy.
    """
    lv = common.str2device(c, lv)
    service = c.root.cimv2.LMI_StorageConfigurationService.first_instance()
    (ret, outparams, err) = service.SyncDeleteLV(TheElement=lv)
    if ret != 0:
        raise LmiFailed("Cannot delete the LV: %s."
                % (service.DeleteLV.DeleteLVValues.value_name(ret),))

def get_vgs(c):
    """
    Retrieve list of all volume groups on the system.

    :rtype: list of LMIInstance/LMI_VGStoragePool
    """
    for vg in c.root.cimv2.LMI_VGStoragePool.instances():
        yield vg

def create_vg(c, devices, name, extent_size=None):
    """
    Create new Volume Group from given devices.

    :type devices: list of LMIInstance/CIM_StorageExtent or list of strings
    :param device: Devices to add to the Volume Group.
    :type name: string
    :param name: Name of the Volume gGoup.
    :type extent_size: int
    :param extent_size: Extent size in bytes.
    :rtype: LMIInstance/LMI_VGStoragePool
    """
    devs = [common.str2device(c, device) for device in devices]
    args = { 'InExtents': devs,
            'ElementName': name}
    goal = None

    try:
        if extent_size:
            # create (and use) VGStorageSetting
            caps = c.root.cimv2.LMI_VGStorageCapabilities.first_instance()
            (ret, outparams, err) = caps.CreateVGStorageSetting(
                    InExtents=devs)
            if ret != 0:
                raise LmiFailed("Cannot create setting for the volume group: %s."
                    % (caps.CreateVGStorageSetting.CreateVGStorageSettingValues.value_name(ret),))
            goal = outparams['Setting']
            goal.ExtentSize = extent_size
            (ret, outparams, err) = goal.push()
            if ret != 0:
                raise LmiFailed("Cannot modify setting for the volume group: %d."
                        % ret)
            args['Goal'] = goal

        service = c.root.cimv2.LMI_StorageConfigurationService.first_instance()
        (ret, outparams, err) = service.SyncCreateOrModifyVG(**args)
        if ret != 0:
            raise LmiFailed("Cannot create the volume group: %s."
                    % (service.CreateOrModifyVG.CreateOrModifyVGValues.value_name(ret),))
    finally:
        if goal:
            goal.delete()

    return outparams['Pool']


def delete_vg(c, vg):
    """
    Destroy given Volume Group.

    :type vg: LMIInstance/LMI_VGStoragePool or string
    :param vg: Volume Group to delete.
    """
    vg = str2vg(c, vg)
    service = c.root.cimv2.LMI_StorageConfigurationService.first_instance()
    (ret, outparams, err) = service.SyncDeleteVG(Pool=vg)
    if ret != 0:
        raise LmiFailed("Cannot delete the VG: %s."
                % (service.DeleteVG.DeleteVGValues.value_name(ret),))

def get_vg_lvs(c, vg):
    """
    Return list of Logical Volumes on given Volume Group.

    :type vg: LMIInstance/LMI_VGStoragePool or string
    :param vg: Volume Group to examine.
    :rtype: list of LMIInstance/LMI_LVStorageExtent
    """
    vg = str2vg(c, vg)
    return vg.associators(AssocClass="LMI_LVAllocatedFromStoragePool")

def get_lv_vg(c, lv):
    """
    Return Volume Group of given Logical Volume.

    :type lv: LMIInstance/LMI_LVStorageExtent or string
    :param lv: Logical Volume to examine.
    :rtype: LMIInstance/LMI_VGStoragePool
    """
    lv = common.str2device(c, lv)
    return lv.first_associator(AssocClass="LMI_LVAllocatedFromStoragePool")

def get_vg_pvs(c, vg):
    """
    Return Physical Volumes of given Volume Group.

    :type vg: LMIInstance/LMI_VGStoragePool or string
    :param vg: Volume Group to examine.
    :rtype: list of LMIInstance/CIM_StorageExtent
    """
    vg = str2vg(c, vg)
    return vg.associators(AssocClass="LMI_VGAssociatedComponentExtent")