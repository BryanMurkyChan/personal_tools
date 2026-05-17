"""小红书数据模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ImageInfo(BaseModel):
    url: str = ""
    width: int = 0
    height: int = 0
    file_id: str = ""
    trace_id: str = ""


class UserInfo(BaseModel):
    user_id: str = ""
    nickname: str = ""
    avatar_url: str = ""


class NoteDetail(BaseModel):
    note_id: str
    title: str = ""
    desc: str = ""
    type: str = "normal"  # "normal" 或 "video"
    video_url: str = ""
    video_cover: str = ""
    images: list[ImageInfo] = Field(default_factory=list)
    author: UserInfo = Field(default_factory=UserInfo)
    like_count: int = 0
    collect_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    create_time: int = 0  # unix timestamp
    update_time: int = 0
    tags: list[str] = Field(default_factory=list)
    ip_location: str = ""
    xsec_token: str = ""

    @property
    def create_time_str(self) -> str:
        if self.create_time:
            return datetime.fromtimestamp(self.create_time).strftime("%Y-%m-%d %H:%M:%S")
        return ""


class Comment(BaseModel):
    comment_id: str
    content: str = ""
    user: UserInfo = Field(default_factory=UserInfo)
    like_count: int = 0
    create_time: int = 0
    ip_location: str = ""
    sub_comments: list["Comment"] = Field(default_factory=list)
    sub_comment_count: int = 0
    sub_comment_cursor: str = ""
    sub_comment_has_more: bool = False
    parent_comment_id: str = ""
    is_author: bool = False
    is_top: bool = False

    @property
    def create_time_str(self) -> str:
        if self.create_time:
            return datetime.fromtimestamp(self.create_time).strftime("%Y-%m-%d %H:%M:%S")
        return ""


class PostData(BaseModel):
    """单篇帖子的完整数据容器。"""
    note: NoteDetail
    comments: list[Comment] = Field(default_factory=list)
    fetch_time: str = ""
    url: str = ""


# ---- API响应解析辅助函数 ----

def parse_note_from_api(data: dict) -> NoteDetail | None:
    """从 /api/sns/web/v1/feed 响应中解析帖子详情。

    响应结构（小红书2026）：
      data.items[0].id  → note_id
      data.items[0].note_card.title  → 标题
      data.items[0].note_card.user  → 作者信息
      data.items[0].note_card.interact_info  → 互动数据
    """
    items = data.get("data", {}).get("items", [])
    if not items:
        return None
    item = items[0]
    note_card = item.get("note_card", {})
    interact = note_card.get("interact_info", {})
    user = note_card.get("user", {})

    images = []
    for img in note_card.get("image_list", []):
        url = img.get("url_default", "") or img.get("url", "")
        # url_default是高清图，优先使用；info_list内的url是不同尺寸
        if not url and img.get("info_list"):
            url = img["info_list"][0].get("url", "")
        images.append(ImageInfo(
            url=url,
            width=img.get("width", 0),
            height=img.get("height", 0),
            file_id=img.get("file_id", ""),
            trace_id=img.get("trace_id", ""),
        ))

    # 视频
    video_url = ""
    video_cover = ""
    if video_info := note_card.get("video", {}):
        video_url = video_info.get("master_url", "")
        video_cover = video_info.get("image", {}).get("first_frame_fileid", "")

    # 标签
    tags = [t.get("name", "") for t in note_card.get("tag_list", []) if t.get("name")]

    return NoteDetail(
        note_id=item.get("id", ""),
        title=note_card.get("title", ""),
        desc=note_card.get("desc", ""),
        type=note_card.get("type", "normal"),
        video_url=video_url,
        video_cover=video_cover,
        images=images,
        author=UserInfo(
            user_id=user.get("user_id", ""),
            nickname=user.get("nickname", ""),
            avatar_url=user.get("avatar", ""),
        ),
        like_count=interact.get("liked_count", 0),
        collect_count=interact.get("collected_count", 0),
        comment_count=interact.get("comment_count", 0),
        share_count=interact.get("share_count", 0),
        create_time=note_card.get("time", 0),
        update_time=note_card.get("last_update_time", 0),
        tags=tags,
        ip_location=note_card.get("ip_location", ""),
    )


def parse_comments_from_api(data: dict) -> tuple[list[Comment], str, bool]:
    """从评论API响应中解析评论列表。

    Returns:
        (comments, next_cursor, has_more)
    """
    d = data.get("data", {})
    raw_comments = d.get("comments", [])
    next_cursor = d.get("cursor", "")
    has_more = d.get("has_more", False)

    comments = []
    for c in raw_comments:
        user_info = c.get("user_info", {})
        comments.append(Comment(
            comment_id=c.get("id", ""),
            content=c.get("content", ""),
            user=UserInfo(
                user_id=user_info.get("user_id", ""),
                nickname=user_info.get("nickname", ""),
                avatar_url=user_info.get("avatar", ""),
            ),
            like_count=c.get("like_count", 0),
            create_time=c.get("create_time", 0),
            ip_location=c.get("ip_location", ""),
            sub_comment_count=c.get("sub_comment_count", 0),
            sub_comment_cursor=c.get("sub_comment_cursor", ""),
            sub_comment_has_more=c.get("sub_comment_has_more", False),
            is_author=c.get("is_author", False),
            is_top=c.get("is_top", False),
        ))
    return comments, next_cursor, has_more


def parse_sub_comments_from_api(data: dict) -> tuple[list[Comment], str, bool]:
    """从子评论API响应中解析子评论列表。"""
    return parse_comments_from_api(data)
