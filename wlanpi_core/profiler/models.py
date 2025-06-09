from typing import Optional

from pydantic import BaseModel


class Start(BaseModel):
    channel: Optional[int] = None
    frequency: Optional[int] = None
    interface: Optional[str] = None
    ssid: Optional[str] = None

    # config_file_path: Optional[str] = None
    # files_path: Optional[str] = None

    debug: Optional[bool] = None
    noprep: Optional[bool] = None
    noAP: Optional[bool] = None
    no11r: Optional[bool] = None
    no11ax: Optional[bool] = None
    no11be: Optional[bool] = None
    noprofilertlv: Optional[bool] = None

    wpa3_personal_transition: Optional[bool] = None
    wpa3_personal: Optional[bool] = None
    oui_update: Optional[bool] = None
    no_bpf_filters: Optional[bool] = None
